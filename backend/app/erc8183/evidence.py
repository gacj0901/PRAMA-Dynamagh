"""Deterministic, fail-closed bridge from certified ERC-8183 Jobs to Evidence.

This module deliberately separates the Telegraph commitments from PRAMA's
derived Evidence hash.  G9-A exposes only dry-run and lineage operations.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace
from urllib.request import urlopen

from app.domain.mandates import AcquisitionStatus, AcquisitionTask, Decision, ERC8183Job, Evidence, Mandate, MandateStatus, MandateTransition, StructuralEvaluation, Ticket, UsageEvent
from app.domain.state_machine import transition_mandate
from app.pramagraph.evaluation import decide, digest
from app.tickets.core import build as build_ticket_core, hash_core

VERSION = "telegraph-erc8183-evidence-v0"
SCHEMA = "prama.evidence.erc8183.v0"
CHAIN_ID = 84532
DIAMOND = "0x5a2324aa18613fad4e44bdf0d6c73ec1f6d87ff8"
RECEIVER = "0x055bf3a946d780a4c043b3991c1c733f140f8124"
ZERO_HASH = "0x" + "00" * 32
PURPOSE = "Evaluate certified Telegraph ERC-8183 Job 27 for structural admissibility and issue a PRAMA Decision Ticket."


class SourceValidationError(ValueError):
    """A source guard failed; callers must not admit Evidence."""


def _lower_hash(value: object, code: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-fA-F]{64}", value):
        raise SourceValidationError(code)
    return value.lower()


def _lower_address(value: object, code: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-fA-F]{40}", value):
        raise SourceValidationError(code)
    return value.lower()


def _integer(value: object) -> str:
    if isinstance(value, bool):
        raise SourceValidationError("RESPONSE_INTEGER_INVALID")
    if isinstance(value, int):
        if value < 0:
            raise SourceValidationError("RESPONSE_INTEGER_INVALID")
        return str(value)
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        return str(int(value))
    raise SourceValidationError("RESPONSE_INTEGER_INVALID")


def _gateway(path: str) -> dict:
    with urlopen(os.environ["GATEWAY_URL"] + path, timeout=30) as response:
        return json.loads(response.read())


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise SourceValidationError(code)


def canonical_response(value: object) -> dict:
    if not isinstance(value, dict):
        raise SourceValidationError("TERMINAL_RESPONSE_MISSING")
    addresses = value.get("addresses")
    integers = value.get("integers")
    strings = value.get("strings")
    bools = value.get("bools")
    _require(all(isinstance(items, list) for items in (addresses, integers, strings, bools)), "TERMINAL_RESPONSE_INVALID")
    _require(all(isinstance(item, str) for item in strings), "TERMINAL_RESPONSE_INVALID")
    _require(all(isinstance(item, bool) for item in bools), "TERMINAL_RESPONSE_INVALID")
    return {
        "addresses": [_lower_address(item, "RESPONSE_ADDRESS_INVALID") for item in addresses],
        "integers": [_integer(item) for item in integers],
        "strings": list(strings),
        "bools": list(bools),
    }


@dataclass(frozen=True)
class CertifiedSource:
    core: dict
    response: dict
    validation: str = "VERIFIED"


def reconstruct(job: ERC8183Job, read=_gateway) -> CertifiedSource:
    """Rebuild one Evidence Core from persisted provenance and fresh chain reads."""
    _require(job.state == "TERMINAL", "JOB_NOT_TERMINAL")
    _require(job.telegraph_job_id is not None, "TELEGRAPH_JOB_ID_MISSING")
    _require(job.chain_id == CHAIN_ID, "CHAIN_ID_MISMATCH")
    _require(_lower_address(job.diamond_address, "DIAMOND_INVALID") == DIAMOND, "DIAMOND_MISMATCH")
    _require(_lower_address(job.callback_address, "CALLBACK_INVALID") == RECEIVER, "CALLBACK_ADDRESS_MISMATCH")
    _require(job.callback_verified is True, "CALLBACK_UNVERIFIED")
    output = _lower_hash(job.output_hash, "OUTPUT_HASH_INVALID")
    callback_hash = _lower_hash(job.callback_response_hash, "CALLBACK_HASH_INVALID")
    _require(output != ZERO_HASH, "OUTPUT_HASH_ZERO")
    _require(callback_hash != ZERO_HASH, "CALLBACK_HASH_ZERO")
    terminal_tx = _lower_hash(job.terminal_tx_hash, "TERMINAL_TX_INVALID")
    create_tx = _lower_hash(job.create_tx_hash, "CREATE_TX_INVALID")
    _require(job.terminal_block_number is not None, "TERMINAL_BLOCK_MISSING")
    _require(job.create_block_number is not None, "CREATE_BLOCK_MISSING")

    chain = read(f"/chain/erc8183/jobs/{job.telegraph_job_id}")
    _require(int(chain.get("state", -1)) == 1, "CHAIN_JOB_NOT_TERMINAL")
    _require(_lower_hash(chain.get("output_hash"), "CHAIN_OUTPUT_INVALID") == output, "OUTPUT_HASH_MISMATCH")
    _require(_lower_address(chain.get("callback"), "CHAIN_CALLBACK_INVALID") == RECEIVER, "CHAIN_CALLBACK_MISMATCH")
    terminal = read(f"/chain/erc8183/jobs/{job.telegraph_job_id}/terminal?from_block={job.create_block_number}")
    event = terminal.get("event") if isinstance(terminal, dict) else None
    _require(isinstance(event, dict), "JOB_TERMINAL_MISSING")
    _require(_lower_hash(event.get("tx_hash"), "CHAIN_TERMINAL_TX_INVALID") == terminal_tx, "TERMINAL_TX_MISMATCH")
    _require(int(event.get("block_number", -1)) == int(job.terminal_block_number), "TERMINAL_BLOCK_MISMATCH")
    verification = read(f"/chain/subnet-receiver/verify?job_id={job.telegraph_job_id}&terminal_tx_hash={terminal_tx}")
    _require(verification.get("status") == "VALID", verification.get("failure_code", "CALLBACK_NOT_DELIVERED"))
    _require(verification.get("receiver_code_present") is True, "RECEIVER_CODE_MISSING")
    _require(_lower_address(verification.get("receiver_diamond"), "RECEIVER_DIAMOND_INVALID") == DIAMOND, "RECEIVER_DIAMOND_MISMATCH")
    _require(_lower_hash(verification.get("stored_response_hash"), "STORED_CALLBACK_HASH_INVALID") == callback_hash, "CALLBACK_HASH_MISMATCH")
    _require(_lower_hash(verification.get("expected_response_hash"), "COMPUTED_CALLBACK_HASH_INVALID") == callback_hash, "CALLBACK_HASH_MISMATCH")
    response = canonical_response(verification.get("response"))
    core = {
        "schema": SCHEMA,
        "source_type": "TELEGRAPH_ERC8183",
        "chain_id": CHAIN_ID,
        "diamond_address": DIAMOND,
        "telegraph_job_id": str(job.telegraph_job_id),
        "intent_name": str(job.intent_name),
        "intent_id": _lower_hash(job.intent_id, "INTENT_ID_INVALID"),
        "callback_address": RECEIVER,
        "create_tx_hash": create_tx,
        "create_block_number": int(job.create_block_number),
        "terminal_tx_hash": terminal_tx,
        "terminal_block_number": int(job.terminal_block_number),
        "telegraph_output_hash": output,
        "callback_response_hash": callback_hash,
        "response": response,
    }
    return CertifiedSource(core=core, response=response)


def dry_run(job: ERC8183Job, read=_gateway) -> dict:
    source = reconstruct(job, read)
    content_hash = digest(source.core)
    evidence_set_hash = digest([content_hash])
    structural_state = "STRUCTURALLY_ADMISSIBLE"
    decision_state, reason_codes = decide(structural_state)
    evidence = SimpleNamespace(
        evidence_id="erc8183:84532:" + str(job.telegraph_job_id), content_hash=content_hash,
        normalizer_version=VERSION, admissibility="ADMITTED", provenance_status="VERIFIED",
        source_intent=job.intent_name, source_miner_id=None, source_signal_hash=None,
    )
    mandate = SimpleNamespace(mandate_id="erc8183:84532:" + str(job.telegraph_job_id), mandate_type="ERC8183_CERTIFIED", constraints={"ticket_subject_id": "erc8183:84532:" + str(job.telegraph_job_id)})
    evaluation = SimpleNamespace(evaluator="PRAMAGRAPH", evaluator_version="pramagraph-structural-v0", structural_state=structural_state, evidence_set_hash=evidence_set_hash)
    decision = SimpleNamespace(state=decision_state, policy_version="prama-gate-v0", reason_codes=reason_codes)
    ticket_core = build_ticket_core(mandate, decision, evaluation, [evidence], [], [])
    return {
        "source_validation": source.validation,
        "evidence_core": source.core,
        "content_hash": content_hash,
        "evidence_set_hash": evidence_set_hash,
        "structural_state": structural_state,
        "decision_state": decision_state,
        "reason_codes": reason_codes,
        "ticket_core": ticket_core,
        "ticket_hash": hash_core(ticket_core),
    }


def promotion_status(session, erc8183_job_id: str) -> str:
    """Bounded future promotion guard: only a persisted local source ID is accepted."""
    job = session.get(ERC8183Job, erc8183_job_id)
    if job is None:
        return "ERC8183_JOB_MISSING"
    existing = session.query(Evidence).filter_by(erc8183_job_id=erc8183_job_id, normalizer_version=VERSION).one_or_none()
    return "ALREADY_PROMOTED" if existing else "READY_TO_PROMOTE"


def promote_verified_erc8183_job(session, erc8183_job_id: str, read=_gateway, *, persist: bool = False) -> dict:
    """Bounded promotion entry point.

    Its sole caller input is the persisted local job ID.  G9-A intentionally
    permits only dry-runs; the future live gate must opt in explicitly.
    """
    status = promotion_status(session, erc8183_job_id)
    if status != "READY_TO_PROMOTE":
        return {"status": status}
    job = session.get(ERC8183Job, erc8183_job_id)
    result = dry_run(job, read)
    if not persist:
        return {"status": "DRY_RUN", "purpose": PURPOSE, **result}
    try:
        source_job = session.get(ERC8183Job, erc8183_job_id)
        mandate = Mandate(actor_id="erc8183-adapter", text=PURPOSE, mandate_type="ERC8183_CERTIFIED", constraints={"ticket_subject_id": "erc8183:84532:" + str(source_job.telegraph_job_id), "erc8183_job_id": source_job.erc8183_job_id}, max_budget_usdc=Decimal("0.000000"), status=MandateStatus.RECEIVED.value)
        session.add(mandate); session.flush()
        session.add_all([
            MandateTransition(mandate_id=mandate.mandate_id, from_status=None, to_status=MandateStatus.RECEIVED.value, reason="certified ERC-8183 promotion"),
            UsageEvent(mandate_id=mandate.mandate_id, event_type="MANDATE_CREATED", metadata_={"erc8183_job_id": source_job.erc8183_job_id}),
        ])
        transition_mandate(session, mandate, MandateStatus.PLANNED, "certified ERC-8183 source")
        acquisition = AcquisitionTask(mandate_id=mandate.mandate_id, query=PURPOSE, requested_intent=source_job.intent_name, required=True, status=AcquisitionStatus.SUCCEEDED.value, ordinal=0, telegraph_job_id=source_job.telegraph_job_id, intent_id=source_job.intent_id, callback_address=source_job.callback_address, tx_hash=source_job.terminal_tx_hash, block_number=source_job.terminal_block_number, onchain_output_hash=source_job.output_hash)
        session.add(acquisition)
        transition_mandate(session, mandate, MandateStatus.ACQUIRING, "bind certified ERC-8183 source")
        evidence = Evidence(mandate_id=mandate.mandate_id, acquisition_id=acquisition.acquisition_id, telegraph_call_id=None, erc8183_job_id=source_job.erc8183_job_id, evidence_type="TELEGRAPH_ERC8183_RESULT", source_kind="TELEGRAPH_ERC8183", source_intent=source_job.intent_name, source_miner_id=None, source_signal_hash=None, normalized_payload=result["evidence_core"], content_hash=result["content_hash"], normalizer_version=VERSION, provenance_status="VERIFIED", admissibility="ADMITTED", limitation_codes=[])
        session.add(evidence); session.flush()
        if digest(evidence.normalized_payload) != result["content_hash"]:
            raise RuntimeError("EVIDENCE_HASH_MISMATCH")
        session.add(UsageEvent(mandate_id=mandate.mandate_id, acquisition_id=acquisition.acquisition_id, event_type="ERC8183_EVIDENCE_PROMOTED", metadata_={"erc8183_job_id": source_job.erc8183_job_id, "content_hash": evidence.content_hash}))
        transition_mandate(session, mandate, MandateStatus.EVALUATING)
        transition_mandate(session, mandate, MandateStatus.DECIDING)
        evaluation = StructuralEvaluation(mandate_id=mandate.mandate_id, evaluator="PRAMAGRAPH", evaluator_version="pramagraph-structural-v0", evidence_set_hash=result["evidence_set_hash"], admitted_evidence_ids=[evidence.evidence_id], limited_evidence_ids=[], rejected_evidence_ids=[], limitation_codes=[], contradiction_codes=[], structural_state=result["structural_state"], evaluation_payload={"source":"ERC8183"})
        session.add(evaluation); session.flush()
        if evaluation.evidence_set_hash != digest([evidence.content_hash]):
            raise RuntimeError("EVIDENCE_SET_HASH_MISMATCH")
        session.add(UsageEvent(mandate_id=mandate.mandate_id, event_type="PRAMAGRAPH_EVALUATED", metadata_={"evaluation_id": evaluation.evaluation_id}))
        decision = Decision(mandate_id=mandate.mandate_id, evaluation_id=evaluation.evaluation_id, state=result["decision_state"], policy_version="prama-gate-v0", evidence_set_hash=evaluation.evidence_set_hash, reason_codes=result["reason_codes"], decision_payload={})
        session.add(decision); session.flush()
        transition_mandate(session, mandate, MandateStatus.DECIDED)
        session.add(UsageEvent(mandate_id=mandate.mandate_id, event_type="DECISION_CREATED", metadata_={"decision_id": decision.decision_id}))
        ticket_core = build_ticket_core(mandate, decision, evaluation, [evidence], [], [acquisition])
        ticket_hash = hash_core(ticket_core)
        if ticket_hash != result["ticket_hash"]:
            raise RuntimeError("TICKET_HASH_MISMATCH")
        ticket = Ticket(mandate_id=mandate.mandate_id, decision_id=decision.decision_id, schema_version="prama.ticket.v0", canonical_payload=ticket_core, ticket_hash=ticket_hash, hash_algorithm="keccak256", anchor_status="LOCAL_ONLY")
        session.add(ticket); session.flush()
        transition_mandate(session, mandate, MandateStatus.TICKETED)
        source_job.mandate_id = mandate.mandate_id; source_job.ticket_id = ticket.ticket_id
        session.add(UsageEvent(mandate_id=mandate.mandate_id, event_type="TICKET_CREATED", metadata_={"ticket_id": ticket.ticket_id}))
        session.commit()
        return {"status": "TICKETED", "mandate_id": mandate.mandate_id, "evidence_id": evidence.evidence_id, "evaluation_id": evaluation.evaluation_id, "decision_id": decision.decision_id, "ticket_id": ticket.ticket_id, **result}
    except Exception:
        session.rollback()
        raise


def lineage(session, erc8183_job_id: str) -> dict:
    job = session.get(ERC8183Job, erc8183_job_id)
    if job is None:
        raise KeyError("ERC8183_JOB_MISSING")
    evidence = session.query(Evidence).filter_by(erc8183_job_id=erc8183_job_id, normalizer_version=VERSION).one_or_none()
    evaluation = session.query(StructuralEvaluation).filter_by(mandate_id=evidence.mandate_id).one_or_none() if evidence else None
    decision = session.query(Decision).filter_by(evaluation_id=evaluation.evaluation_id).one_or_none() if evaluation else None
    ticket = session.query(Ticket).filter_by(decision_id=decision.decision_id).one_or_none() if decision else None
    return {
        "erc8183_job_id": job.erc8183_job_id,
        "telegraph_job_id": job.telegraph_job_id,
        "telegraph_output_hash": job.output_hash,
        "callback_response_hash": job.callback_response_hash,
        "callback_verified": job.callback_verified,
        "intent_id": job.intent_id,
        "terminal_tx_hash": job.terminal_tx_hash,
        "evidence_id": evidence.evidence_id if evidence else None,
        "evidence_content_hash": evidence.content_hash if evidence else None,
        "evaluation_id": evaluation.evaluation_id if evaluation else None,
        "evidence_set_hash": evaluation.evidence_set_hash if evaluation else None,
        "decision_id": decision.decision_id if decision else None,
        "decision_state": decision.state if decision else None,
        "ticket_id": ticket.ticket_id if ticket else None,
        "ticket_hash": ticket.ticket_hash if ticket else None,
        "anchor_status": ticket.anchor_status if ticket else None,
    }


def replay_persisted(session, erc8183_job_id: str) -> dict:
    """DB-only replay: no Gateway/RPC access and no writes."""
    job = session.get(ERC8183Job, erc8183_job_id)
    if job is None or not job.mandate_id:
        raise KeyError("ERC8183_PROMOTION_MISSING")
    evidence = session.query(Evidence).filter_by(erc8183_job_id=erc8183_job_id, normalizer_version=VERSION).one()
    evaluation = session.query(StructuralEvaluation).filter_by(mandate_id=job.mandate_id).one()
    decision = session.query(Decision).filter_by(evaluation_id=evaluation.evaluation_id).one()
    ticket = session.query(Ticket).filter_by(decision_id=decision.decision_id).one()
    mandate = session.get(Mandate, job.mandate_id)
    acquisition = session.query(AcquisitionTask).filter_by(mandate_id=job.mandate_id).one()
    content_hash = digest(evidence.normalized_payload)
    evidence_set_hash = digest([content_hash])
    state = "STRUCTURALLY_ADMISSIBLE" if evidence.admissibility == "ADMITTED" else "STRUCTURALLY_BLOCKED"
    decision_state, reason_codes = decide(state)
    core = build_ticket_core(mandate, decision, evaluation, [evidence], [], [acquisition])
    return {"content_hash": content_hash, "evidence_set_hash": evidence_set_hash, "structural_state": state, "decision_state": decision_state, "reason_codes": reason_codes, "ticket_hash": hash_core(core), "matches": content_hash == evidence.content_hash and evidence_set_hash == evaluation.evidence_set_hash and decision_state == decision.state and reason_codes == decision.reason_codes and core == ticket.canonical_payload and hash_core(core) == ticket.ticket_hash}
