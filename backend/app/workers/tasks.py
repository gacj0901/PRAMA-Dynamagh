import json, os
from time import sleep
from datetime import datetime, timezone
from decimal import Decimal
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import redis
from app.workers.celery_app import celery_app
from app.persistence.database import SessionLocal
from app.domain.mandates import AcquisitionTask, AcquisitionStatus, AnchorAttempt, Mandate, MandateStatus, TelegraphCall, Ticket, UsageEvent, Evidence, StructuralEvaluation, Decision
from app.domain.state_machine import transition_mandate
from app.pramagraph.evaluation import classify, decide, digest
from app.tickets.service import issue as issue_ticket
from app.autonomy.service import claim_run, execute_claimed, finalize_http_run, recover_runs, schedule_due
from app.domain.mandates import AutonomyPolicy
from app.public_safety import release_public_manual_reservation, settle_public_manual_spend, verify_public_manual_reservation
from app.redis_config import redis_url

def now(): return datetime.now(timezone.utc)


@celery_app.task(name="prama.autonomy_tick")
def autonomy_tick():
    """Private worker scheduler; policy/global controls fail closed.

    PostgreSQL row locks in ``claim_run`` provide the durable lease.  This
    task deliberately has no public API counterpart.
    """
    session = SessionLocal()
    try:
        recovered = recover_runs(session)
        session.commit()
        scheduled = claimed = completed = 0
        policies = session.query(AutonomyPolicy).filter_by(enabled=True, state="ACTIVE").all()
        for policy in policies:
            run = schedule_due(session, policy)
            if run is None:
                continue
            scheduled += 1
            session.commit()
            run = claim_run(session, run.run_id)
            if run is None:
                session.rollback()
                continue
            claimed += 1
            outcome = execute_claimed(session, run)
            if outcome == "COMPLETED":
                completed += 1
            session.commit()
            if outcome == "ACQUISITION_QUEUED":
                acquisition = session.query(AcquisitionTask).filter_by(mandate_id=run.mandate_id).one()
                execute_acquisition.delay(run.mandate_id, acquisition.acquisition_id)
        return {"recovered": len(recovered), "scheduled": scheduled, "claimed": claimed, "completed": completed}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
@celery_app.task(name="prama.execute_acquisition", bind=True)
def execute_acquisition(self, mandate_id: str, acquisition_id: str):
    lock = redis.from_url(redis_url()); key = f"prama:acquisition:{acquisition_id}"
    if not lock.set(key, "1", nx=True, ex=300): return "LOCKED"
    s = SessionLocal(); network_attempted = False; public_reservation = False
    try:
        task = s.get(AcquisitionTask, acquisition_id); mandate = s.get(Mandate, mandate_id)
        if not task or not mandate: return "INVALID_MANDATE"
        if task.status == AcquisitionStatus.SUCCEEDED.value: return "ALREADY_COMPLETED"
        # A delivery after a terminal result must never create a second paid
        # attempt.  The persisted reservation stays auditable and fail-closed.
        if task.status == AcquisitionStatus.FAILED.value: return "ALREADY_FAILED"
        if task.status == AcquisitionStatus.RUNNING.value: return "ALREADY_RUNNING"
        if mandate.status == MandateStatus.RECEIVED.value: transition_mandate(s, mandate, MandateStatus.PLANNED)
        task.status = AcquisitionStatus.RUNNING.value; task.attempt_count += 1; task.started_at = now()
        if mandate.status == MandateStatus.PLANNED.value: transition_mandate(s, mandate, MandateStatus.ACQUIRING)
        spent = sum((c.cost_usd or 0 for c in s.query(TelegraphCall).filter_by(mandate_id=mandate_id, status="SUCCEEDED")), Decimal("0"))
        remaining = Decimal(mandate.max_budget_usdc) - spent
        if remaining <= 0: raise RuntimeError("BUDGET_EXHAUSTED")
        if mandate.origin == "MANUAL":
            reservation = verify_public_manual_reservation(s, mandate_id, Decimal(mandate.max_budget_usdc))
            if remaining > reservation.reserved_usdc:
                raise RuntimeError("PUBLIC_SPEND_AUTHORIZATION_INVALID")
            public_reservation = True
        s.add(UsageEvent(mandate_id=mandate_id, acquisition_id=acquisition_id, event_type="TELEGRAPH_REQUEST", metadata_={}))
        s.commit()
        data = json.dumps({"query": task.query, "context": {}, "causal_request_id": mandate_id, "budget_usdc": str(remaining)}).encode()
        req = Request(os.environ["GATEWAY_URL"] + "/ask", data=data, headers={"content-type": "application/json"}, method="POST")
        network_attempted = True
        with urlopen(req, timeout=45) as r: raw = json.loads(r.read())
        if not raw.get("miner_id") or not raw.get("intent") or not raw.get("signal_hash"): raise RuntimeError("TELEGRAPH_INVALID_RESPONSE")
        actual_cost = Decimal(str(raw.get("cost_usd") or "0"))
        if actual_cost > Decimal(mandate.max_budget_usdc): raise RuntimeError("BUDGET_EXHAUSTED")
        if public_reservation: settle_public_manual_spend(s, mandate_id, actual_cost)
        call = TelegraphCall(mandate_id=mandate_id, acquisition_id=acquisition_id, causal_request_id=mandate_id, miner_id=str(raw.get("miner_id")), miner_name=raw.get("miner_name"), intent=raw.get("intent"), signal_hash=raw.get("signal_hash"), cost_usd=actual_cost, duration_ms=raw.get("duration_ms"), reasoning=raw.get("reasoning"), warnings=raw.get("warnings", []), raw_response=raw, status="SUCCEEDED", completed_at=now())
        s.add(call); task.status = AcquisitionStatus.SUCCEEDED.value; task.completed_at = now(); transition_mandate(s, mandate, MandateStatus.EVALUATING)
        s.add_all([UsageEvent(mandate_id=mandate_id, acquisition_id=acquisition_id, event_type="TELEGRAPH_RESPONSE", metadata_={}), UsageEvent(mandate_id=mandate_id, acquisition_id=acquisition_id, event_type="ACQUISITION_COMPLETED", metadata_={})])
        s.commit(); return evaluate_mandate(mandate_id)
    except Exception as e:
        raw_code = str(e)
        known = {"BUDGET_EXHAUSTED", "TELEGRAPH_INVALID_RESPONSE", "PUBLIC_SPEND_AUTHORIZATION_INVALID", "PUBLIC_SPEND_AUTHORIZATION_UNAVAILABLE", "PUBLIC_SPEND_SETTLEMENT_INVALID"}
        code = raw_code if raw_code in known else "GATEWAY_UNAVAILABLE"
        # Before the outbound request, the reservation is certainly unspent and
        # can be released.  After any network attempt it is deliberately held
        # rather than risking a second x402 payment after an uncertain result.
        if public_reservation and not network_attempted:
            try:
                release_public_manual_reservation(s, mandate_id)
            except Exception:
                s.rollback()
                code = "PUBLIC_SPEND_AUTHORIZATION_UNAVAILABLE"
        task = s.get(AcquisitionTask, acquisition_id); mandate = s.get(Mandate, mandate_id)
        if task: task.status = AcquisitionStatus.FAILED.value; task.failure_code = code
        if mandate and mandate.status not in {"FAILED", "TICKETED"}: transition_mandate(s, mandate, MandateStatus.FAILED, code)
        if mandate and mandate.origin == "AUTONOMOUS": finalize_http_run(s, mandate_id, failure_code=code)
        s.commit(); return code
    finally:
        lock.delete(key); s.close()

@celery_app.task(name="prama.evaluate_mandate")
def evaluate_mandate(mandate_id):
    s=SessionLocal()
    try:
        mandate=s.get(Mandate,mandate_id)
        if mandate.status=="DECIDED": return "ALREADY_DECIDED"
        calls=s.query(TelegraphCall).filter_by(mandate_id=mandate_id,status="SUCCEEDED").all()
        if mandate.status=="EVALUATING": transition_mandate(s,mandate,MandateStatus.DECIDING)
        evidence=[]
        for c in calls:
            existing=s.query(Evidence).filter_by(telegraph_call_id=c.telegraph_call_id).one_or_none()
            if existing: evidence.append(existing); continue
            try:
                with urlopen(os.environ["GATEWAY_URL"]+"/signals/"+c.signal_hash,timeout=20) as x: verified=x.status==200
            except: verified=False
            if mandate.origin == "AUTONOMOUS":
                policy=s.get(AutonomyPolicy, mandate.autonomy_policy_id)
                if policy and policy.strict_verification and not verified:
                    transition_mandate(s, mandate, MandateStatus.FAILED, "STRICT_PROVENANCE_FAILED")
                    finalize_http_run(s, mandate_id, failure_code="STRICT_PROVENANCE_FAILED")
                    s.commit(); return "STRICT_PROVENANCE_FAILED"
            normalized={"intent":c.intent,"result":c.raw_response.get("result"),"miner_id":c.miner_id,"signal_hash":c.signal_hash,"warnings":c.warnings}; adm,codes=classify(c,verified)
            e=Evidence(mandate_id=mandate_id,acquisition_id=c.acquisition_id,telegraph_call_id=c.telegraph_call_id,evidence_type="TELEGRAPH_RESULT",source_kind="TELEGRAPH",source_intent=c.intent,source_miner_id=c.miner_id,source_signal_hash=c.signal_hash,normalized_payload=normalized,content_hash=digest(normalized),normalizer_version="telegraph-evidence-v0",provenance_status="VERIFIED" if verified else "FAILED",admissibility=adm,limitation_codes=codes); s.add(e); evidence.append(e)
        s.flush(); esh=digest([e.content_hash for e in sorted(evidence,key=lambda x:x.evidence_id)])
        rejected=[e.evidence_id for e in evidence if e.admissibility=="REJECTED"]; limited=[e.evidence_id for e in evidence if e.admissibility=="LIMITED"]; admitted=[e.evidence_id for e in evidence if e.admissibility=="ADMITTED"]; structural="STRUCTURALLY_BLOCKED" if not evidence or rejected else ("STRUCTURALLY_LIMITED" if limited else "STRUCTURALLY_ADMISSIBLE")
        ev=StructuralEvaluation(mandate_id=mandate_id,evaluator="PRAMAGRAPH",evaluator_version="pramagraph-structural-v0",evidence_set_hash=esh,admitted_evidence_ids=admitted,limited_evidence_ids=limited,rejected_evidence_ids=rejected,limitation_codes=sum((e.limitation_codes for e in evidence),[]),contradiction_codes=[],structural_state=structural,evaluation_payload={}); s.add(ev); s.flush(); state,reasons=decide(structural); s.add(Decision(mandate_id=mandate_id,evaluation_id=ev.evaluation_id,state=state,policy_version="prama-gate-v0",evidence_set_hash=esh,reason_codes=reasons,decision_payload={})); transition_mandate(s,mandate,MandateStatus.DECIDED); s.add_all([UsageEvent(mandate_id=mandate_id,event_type="EVIDENCE_CREATED",metadata_={}),UsageEvent(mandate_id=mandate_id,event_type="EVALUATION_COMPLETED",metadata_={}),UsageEvent(mandate_id=mandate_id,event_type="DECISION_CREATED",metadata_={})]); s.commit(); result=issue_ticket(s,mandate_id)[1]
        if mandate.origin == "AUTONOMOUS": finalize_http_run(s, mandate_id); s.commit()
        return result
    finally: s.close()


@celery_app.task(name="prama.execute_ticket_anchor")
def execute_ticket_anchor(ticket_id: str):
    """Deferred G6 write path. It is never called by a read-only preflight."""
    s = SessionLocal()
    try:
        ticket = s.get(Ticket, ticket_id)
        attempt = s.query(AnchorAttempt).filter_by(ticket_id=ticket_id).one_or_none()
        if not ticket or not attempt:
            return "ANCHOR_ATTEMPT_MISSING"
        if attempt.status == "CONFIRMED":
            return "ALREADY_ANCHORED"
        from app.tickets.service import verify
        if verify(s, ticket)["status"] != "VALID":
            attempt.status = "FAILED"; attempt.failure_code = "TICKET_INVALID"; ticket.anchor_status = "ANCHOR_FAILED"; s.commit(); return "TICKET_INVALID"
        if not attempt.tx_hash:
            token = os.environ.get("PRAMA_GATEWAY_INTERNAL_TOKEN")
            if not token:
                attempt.status = "FAILED"; attempt.failure_code = "GATEWAY_INTERNAL_TOKEN_MISSING"; ticket.anchor_status = "ANCHOR_FAILED"; s.commit(); return attempt.failure_code
            data = json.dumps({"ticket_hash": ticket.ticket_hash}).encode()
            request = Request(os.environ["GATEWAY_URL"] + "/chain/ticket-anchors", data=data, headers={"content-type": "application/json", "x-prama-internal-token": token}, method="POST")
            with urlopen(request, timeout=120) as response:
                result = json.loads(response.read())
            attempt.status = "SUBMITTED"; attempt.tx_hash = result.get("tx_hash"); attempt.submitted_at = now(); s.commit()
        else:
            result = {"contract_address": attempt.contract_address}
        for _ in range(24):
            with urlopen(os.environ["GATEWAY_URL"] + f"/chain/ticket-anchors/{ticket.ticket_hash}/transactions/{attempt.tx_hash}", timeout=20) as response:
                confirmation = json.loads(response.read())
            if confirmation.get("status") == "PENDING":
                sleep(5); continue
            if confirmation.get("status") != "CONFIRMED":
                attempt.status = "FAILED"; attempt.failure_code = confirmation.get("failure_code", "ANCHOR_RECEIPT_MISMATCH"); ticket.anchor_status = "ANCHOR_FAILED"; s.commit(); return attempt.failure_code
            attempt.status = "CONFIRMED"; attempt.failure_code = None; attempt.block_number = int(confirmation["block_number"]); attempt.block_hash = confirmation["block_hash"]; attempt.confirmed_at = now()
            ticket.anchor_status = "ANCHORED"; ticket.chain_id = 84532; ticket.contract_address = result["contract_address"]; ticket.tx_hash = attempt.tx_hash; ticket.block_number = attempt.block_number; ticket.block_hash = attempt.block_hash
            s.add(UsageEvent(mandate_id=ticket.mandate_id, event_type="TICKET_ANCHORED", metadata_={"ticket_id": ticket.ticket_id, "anchor_attempt_id": attempt.anchor_attempt_id}))
            s.commit(); return "ANCHORED"
        return "ANCHOR_RECEIPT_TIMEOUT"
    except Exception:
        if 'attempt' in locals() and attempt:
            attempt.status = "FAILED"; attempt.failure_code = "ANCHOR_GATEWAY_UNAVAILABLE"
        if 'ticket' in locals() and ticket:
            ticket.anchor_status = "ANCHOR_FAILED"
        s.commit()
        return "ANCHOR_GATEWAY_UNAVAILABLE"
    finally:
        s.close()


def _gateway_json(path, method="GET", payload=None, authenticated=False):
    headers = {"content-type": "application/json"}
    if authenticated:
        token = os.environ.get("PRAMA_GATEWAY_INTERNAL_TOKEN")
        if not token: raise RuntimeError("GATEWAY_INTERNAL_TOKEN_MISSING")
        headers["x-prama-internal-token"] = token
    body = None if payload is None else json.dumps(payload).encode()
    request = Request(os.environ["GATEWAY_URL"] + path, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=30) as response: return json.loads(response.read())
    except HTTPError as error:
        try: code = json.loads(error.read()).get("code", f"HTTP_{error.code}")
        except Exception: code = f"HTTP_{error.code}"
        raise RuntimeError(code) from error


def _micro_usdc(value): return Decimal(str(value)) / Decimal("1000000")


def cancellation_allowed(job) -> bool:
    """Only a funded job may be moved into the bounded cancellation path."""
    return job.state in {"FUNDED", "CANCEL_PENDING"} and job.chain_state == "FUNDED"


def _event_for_job(session, event_type, erc8183_job_id):
    return next((event for event in session.query(UsageEvent).filter_by(event_type=event_type)
                 if event.metadata_.get("erc8183_job_id") == erc8183_job_id), None)


def _record_observation_timeout(session, job):
    """Persist an orchestration timeout without changing the protocol state."""
    if _event_for_job(session, "ERC8183_JOB_OBSERVATION_TIMEOUT", job.erc8183_job_id) is None:
        session.add(UsageEvent(mandate_id=None, event_type="ERC8183_JOB_OBSERVATION_TIMEOUT",
                               metadata_={"erc8183_job_id": job.erc8183_job_id,
                                          "telegraph_job_id": job.telegraph_job_id,
                                          "chain_state": "FUNDED"}))


def _verify_callback(session, job):
    """Read-only callback proof. Terminal protocol state remains durable even when proof is unavailable."""
    if job.callback_address.lower() == "0x0000000000000000000000000000000000000000":
        return "CALLBACK_NOT_CONFIGURED"
    if not job.telegraph_job_id or not job.terminal_tx_hash:
        return "CALLBACK_NOT_DELIVERED"
    try:
        result = _gateway_json(f"/chain/subnet-receiver/verify?job_id={job.telegraph_job_id}&terminal_tx_hash={job.terminal_tx_hash}")
    except Exception:
        job.callback_verified = False
        return "CALLBACK_NOT_DELIVERED"
    stored = result.get("stored_response_hash")
    if result.get("status") != "VALID":
        job.callback_response_hash = stored
        job.callback_verified = False
        return result.get("failure_code", "CALLBACK_NOT_DELIVERED")
    job.callback_response_hash = stored
    job.callback_verified = True
    job.callback_verified_at = now()
    if _event_for_job(session, "ERC8183_CALLBACK_VERIFIED", job.erc8183_job_id) is None:
        session.add(UsageEvent(mandate_id=None, event_type="ERC8183_CALLBACK_VERIFIED",
                               metadata_={"erc8183_job_id": job.erc8183_job_id,
                                          "telegraph_job_id": job.telegraph_job_id,
                                          "callback_response_hash": stored}))
    return "CALLBACK_VERIFIED"


def _mark_terminal(session, job, chain, terminal):
    """Apply a read-only, verified terminal observation to one local job."""
    if int(chain["state"]) != 1 or chain["output_hash"] == "0x" + "00" * 32:
        raise RuntimeError("ERC8183_TERMINAL_INVALID")
    if not terminal or not terminal.get("event"):
        raise RuntimeError("ERC8183_JOBTERMINAL_MISSING")
    if _micro_usdc(chain["miner_payment_micro"]) + _micro_usdc(chain["protocol_fee_micro"]) != _micro_usdc(chain["budget_micro"]):
        raise RuntimeError("ERC8183_ACCOUNTING_MISMATCH")
    job.budget_usdc = _micro_usdc(chain["budget_micro"])
    job.miner_payment_usdc = _micro_usdc(chain["miner_payment_micro"])
    job.protocol_fee_usdc = _micro_usdc(chain["protocol_fee_micro"])
    job.chain_state = "TERMINAL"
    job.output_hash = chain["output_hash"]
    job.terminal_tx_hash = terminal["event"]["tx_hash"]
    job.terminal_block_number = int(terminal["event"]["block_number"])
    job.state = "TERMINAL"
    job.failure_code = None
    job.terminal_at = now()
    if _event_for_job(session, "ERC8183_JOB_TERMINAL", job.erc8183_job_id) is None:
        session.add(UsageEvent(mandate_id=None, event_type="ERC8183_JOB_TERMINAL",
                               metadata_={"erc8183_job_id": job.erc8183_job_id,
                                          "telegraph_job_id": job.telegraph_job_id}))
    _verify_callback(session, job)


@celery_app.task(name="prama.reconcile_erc8183_job")
def reconcile_erc8183_job(erc8183_job_id: str):
    """Read-only recovery path; it never funds, creates, or cancels a job."""
    from app.domain.mandates import ERC8183Job
    s = SessionLocal()
    try:
        job = s.get(ERC8183Job, erc8183_job_id)
        if not job or not job.telegraph_job_id: return "ERC8183_RECONCILE_INVALID"
        if job.failure_code == "ERC8183_JOB_UNRESOLVED":
            _record_observation_timeout(s, job)
        chain = _gateway_json(f"/chain/erc8183/jobs/{job.telegraph_job_id}")
        # A verified terminal observation is immutable.  Re-read the chain and
        # callback proof for reconciliation, but do not rewrite timestamps or
        # artifacts on a delivery of the same task.
        if job.state == "TERMINAL" and job.callback_verified:
            if int(chain["state"]) != 1 or chain["output_hash"] != job.output_hash:
                return "ERC8183_TERMINAL_RECONCILIATION_MISMATCH"
            terminal = _gateway_json(f"/chain/erc8183/jobs/{job.telegraph_job_id}/terminal?from_block={job.create_block_number}")
            if not terminal or not terminal.get("event") or terminal["event"]["tx_hash"] != job.terminal_tx_hash:
                return "ERC8183_TERMINAL_RECONCILIATION_MISMATCH"
            proof = _gateway_json(f"/chain/subnet-receiver/verify?job_id={job.telegraph_job_id}&terminal_tx_hash={job.terminal_tx_hash}")
            if proof.get("status") != "VALID" or proof.get("stored_response_hash") != job.callback_response_hash:
                return "ERC8183_CALLBACK_RECONCILIATION_MISMATCH"
            return "ALREADY_TERMINAL+CALLBACK_ALREADY_VERIFIED"
        if int(chain["state"]) == 0:
            job.state = "FUNDED"; job.chain_state = "FUNDED"; job.failure_code = None; s.commit(); return "FUNDED"
        if int(chain["state"]) == 2:
            job.state = "CANCELLED"; job.chain_state = "CANCELLED"; job.failure_code = None; s.commit(); return "CANCELLED"
        terminal = _gateway_json(f"/chain/erc8183/jobs/{job.telegraph_job_id}/terminal?from_block={job.create_block_number}")
        _mark_terminal(s, job, chain, terminal)
        s.commit()
        return "TERMINAL"
    finally: s.close()


@celery_app.task(name="prama.fund_erc8183_escrow")
def fund_erc8183_escrow(erc8183_job_id: str):
    """G7 funding-only task. It cannot call createJob, Engine, or x402."""
    from app.domain.mandates import ERC8183Job
    s = SessionLocal()
    try:
        job = s.get(ERC8183Job, erc8183_job_id)
        if not job or job.state not in {"PREPARING", "ESCROW_READY"}: return "ERC8183_FUNDING_INVALID_STATE"
        first = _gateway_json("/chain/erc8183/preflight")
        if int(first["job_base_price_micro"]) > int(first["budget_cap_micro"]): return "ERC8183_JOB_BUDGET_EXCEEDED"
        top_up = int(first["top_up_micro"]); job.budget_usdc = _micro_usdc(first["job_base_price_micro"])
        if top_up == 0:
            job.state = "ESCROW_READY"; job.failure_code = None; s.commit(); return "ESCROW_READY"
        if int(first["usdc_allowance_micro"]) < top_up:
            approval = _gateway_json("/chain/erc8183/approve", "POST", {"amount_micro": str(top_up)}, True)
            job.approval_tx_hash = approval["tx_hash"]; job.approval_block_number = int(approval["block_number"]); s.commit()
        second = _gateway_json("/chain/erc8183/preflight")
        if int(second["job_base_price_micro"]) != int(first["job_base_price_micro"]) or int(second["top_up_micro"]) != top_up or int(second["usdc_allowance_micro"]) < top_up:
            return "ERC8183_FUNDING_REPREFLIGHT_REQUIRED"
        deposit = _gateway_json("/chain/erc8183/deposit", "POST", {"amount_micro": str(top_up)}, True)
        job.deposit_tx_hash = deposit["tx_hash"]; job.deposit_block_number = int(deposit["block_number"]); s.commit()
        final = _gateway_json("/chain/erc8183/preflight")
        if int(final["escrow_balance_micro"]) < int(final["required_escrow_micro"]):
            # RPC replicas can briefly lag the mined receipt. Re-read only; never repeat deposit.
            sleep(3); final = _gateway_json("/chain/erc8183/preflight")
        if int(final["escrow_balance_micro"]) < int(final["required_escrow_micro"]): return "ERC8183_ESCROW_INSUFFICIENT"
        job.state = "ESCROW_READY"; job.failure_code = None; s.commit(); return "ESCROW_READY"
    except Exception as error:
        if "job" in locals() and job:
            job.failure_code = str(error)[:100]; s.commit()
        return "ERC8183_FUNDING_FAILED"
    finally: s.close()


@celery_app.task(name="prama.execute_erc8183_job")
def execute_erc8183_job(erc8183_job_id: str):
    """G7 worker path: exact fixture only, no Engine/x402/miner request."""
    from app.domain.mandates import ERC8183Job
    s = SessionLocal()
    try:
        job = s.get(ERC8183Job, erc8183_job_id)
        if not job: return "ERC8183_JOB_MISSING"
        if job.state == "TERMINAL":
            # A job may settle after a bounded original observation window.  A
            # subsequent redelivery must remain chain-read-free, but it can
            # repair the local terminal telemetry exactly once.
            terminal_event = _event_for_job(s, "ERC8183_JOB_TERMINAL", job.erc8183_job_id)
            if terminal_event is None:
                s.add(UsageEvent(mandate_id=None, event_type="ERC8183_JOB_TERMINAL",
                                 metadata_={"erc8183_job_id": job.erc8183_job_id,
                                            "telegraph_job_id": job.telegraph_job_id,
                                            "reconciled_after_late_settlement": True}))
                s.commit()
            if job.callback_verified:
                return "ALREADY_TERMINAL+CALLBACK_ALREADY_VERIFIED"
            if job.callback_address.lower() != "0x0000000000000000000000000000000000000000" and job.telegraph_job_id:
                chain = _gateway_json(f"/chain/erc8183/jobs/{job.telegraph_job_id}")
                terminal = _gateway_json(f"/chain/erc8183/jobs/{job.telegraph_job_id}/terminal?from_block={job.create_block_number}")
                _mark_terminal(s, job, chain, terminal); s.commit()
                return "ALREADY_TERMINAL+CALLBACK_RECONCILED"
            return "ALREADY_TERMINAL"
        preflight = _gateway_json("/chain/erc8183/preflight")
        job.budget_usdc = _micro_usdc(preflight["job_base_price_micro"])
        if not preflight["signer_gas_sufficient"] or int(preflight["job_base_price_micro"]) > int(preflight["budget_cap_micro"]):
            job.state = "FAILED"; job.failure_code = "ERC8183_JOB_BUDGET_EXCEEDED"; s.commit(); return job.failure_code
        # G7 writes require a deliberate operator enablement after read-only preflight.
        if os.environ.get("ERC8183_LIVE_WRITES_ENABLED", "false").lower() != "true":
            job.failure_code = "ERC8183_PREFLIGHT_REQUIRED"; s.commit(); return job.failure_code
        top_up = int(preflight["top_up_micro"])
        if not job.telegraph_job_id and not job.create_tx_hash:
            if top_up:
                if int(preflight["usdc_allowance_micro"]) < top_up:
                    _gateway_json("/chain/erc8183/approve", "POST", {"amount_micro": str(top_up)}, True)
                _gateway_json("/chain/erc8183/deposit", "POST", {"amount_micro": str(top_up)}, True)
                preflight = _gateway_json("/chain/erc8183/preflight")
                if int(preflight["escrow_balance_micro"]) < int(preflight["required_escrow_micro"]): raise RuntimeError("ERC8183_ESCROW_INSUFFICIENT")
            job.state = "ESCROW_READY"; s.commit()
            created = _gateway_json("/chain/erc8183/jobs", "POST", {}, True)
            job.create_tx_hash = created["tx_hash"]; job.state = "SUBMITTED"; job.failure_code = None; s.commit()
        if not job.telegraph_job_id:
            for _ in range(24):
                receipt = _gateway_json(f"/chain/erc8183/transactions/{job.create_tx_hash}/create")
                if receipt["status"] == "PENDING": sleep(5); continue
                if receipt["status"] != "CONFIRMED": raise RuntimeError(receipt.get("failure_code", "ERC8183_JOBCREATED_MISMATCH"))
                job.telegraph_job_id = receipt["job_id"]; job.create_block_number = int(receipt["block_number"]); job.state = "FUNDED"; s.add(UsageEvent(mandate_id=None, event_type="ERC8183_JOB_CREATED", metadata_={"erc8183_job_id": job.erc8183_job_id, "telegraph_job_id": job.telegraph_job_id})); s.commit(); break
            if not job.telegraph_job_id: return "ERC8183_CREATE_RECEIPT_TIMEOUT"
        for _ in range(24):
            chain = _gateway_json(f"/chain/erc8183/jobs/{job.telegraph_job_id}")
            job.budget_usdc = _micro_usdc(chain["budget_micro"]); job.miner_payment_usdc = _micro_usdc(chain["miner_payment_micro"]); job.protocol_fee_usdc = _micro_usdc(chain["protocol_fee_micro"])
            if int(chain["state"]) == 0:
                job.state = "FUNDED"; job.chain_state = "FUNDED"; job.failure_code = None; s.commit(); sleep(5); continue
            if int(chain["state"]) == 2: job.state = "CANCELLED"; s.commit(); return "CANCELLED"
            terminal = _gateway_json(f"/chain/erc8183/jobs/{job.telegraph_job_id}/terminal?from_block={job.create_block_number}")
            _mark_terminal(s, job, chain, terminal); s.commit(); return "TERMINAL"
        job.state = "FUNDED"; job.chain_state = "FUNDED"; job.failure_code = None
        _record_observation_timeout(s, job); s.commit(); return "ERC8183_OBSERVATION_TIMEOUT"
    except Exception as error:
        if "job" in locals() and job:
            job.state = "FAILED"; job.failure_code = str(error)[:100]; s.commit()
        return "ERC8183_FAILED"
    finally: s.close()


@celery_app.task(name="prama.cancel_erc8183_job")
def cancel_erc8183_job(erc8183_job_id: str):
    from app.domain.mandates import ERC8183Job
    s = SessionLocal()
    try:
        job = s.get(ERC8183Job, erc8183_job_id)
        if not job or not cancellation_allowed(job) or not job.telegraph_job_id: return "ERC8183_CANCEL_INVALID"
        if os.environ.get("ERC8183_LIVE_WRITES_ENABLED", "false").lower() != "true": return "ERC8183_PREFLIGHT_REQUIRED"
        result = _gateway_json(f"/chain/erc8183/jobs/{job.telegraph_job_id}/cancel", "POST", {}, True)
        chain = _gateway_json(f"/chain/erc8183/jobs/{job.telegraph_job_id}")
        if int(chain["state"]) != 2: return "ERC8183_CANCEL_READBACK_FAILED"
        job.chain_state = "CANCELLED"; job.state = "CANCELLED"; job.cancel_tx_hash = result["tx_hash"]; job.cancel_block_number = int(result["block_number"]); job.cancelled_at = now(); s.add(UsageEvent(mandate_id=None, event_type="ERC8183_JOB_CANCELLED", metadata_={"erc8183_job_id": job.erc8183_job_id})); s.commit(); return "CANCELLED"
    finally: s.close()
