"""Authority checkpoint for the autonomous execution boundary."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session
from app.persistence.database import SessionLocal

from app.agents.observation import build_o_agent_stream
from app.authority.autonomy import G13PolicyInput, evaluate_g13_policy
from app.authority.recovery import (
    G13_OPERATOR_RECOVERY_POLICY_VERSION,
    latest_operator_recovery,
)
from app.authority.composition import (
    AuthorityCompositionInput,
    evaluate_authority_composition,
)
from app.authority.epistemic import EpistemicPolicyInput, evaluate_epistemic_policy
from app.domain.mandates import (
    AcquisitionTask,
    AutonomyRun,
    EpistemicEvaluation,
    Mandate,
    Decision,
    PublicManualSpendReservation,
    AgentIdentity,
)
from app.epistemic.contracts import canonical_hash
from app.policy_gate.substrate import PolicyEvaluationCore, persist_policy_evaluation


logger = logging.getLogger(__name__)
RUNTIME_CHECKPOINT_VERSION = "pre-next-action-authority-check-v0.1"
G13_ENFORCEMENT_WINDOW_SIZE = 16
G13_PRE_ACTION_EXPECTED_MISSING = (
    "EVIDENCE_NOT_PRESENT",
    "EVALUATION_NOT_PRESENT",
    "LOCAL_DECISION_NOT_PRESENT",
    "TELEGRAPH_LATENCY_NOT_AVAILABLE",
    "TICKET_NOT_PRESENT",
)


@dataclass(frozen=True)
class AuthorityShadowCheckpoint:
    epistemic: PolicyEvaluationCore | None
    longitudinal: PolicyEvaluationCore
    composition: PolicyEvaluationCore


def evaluate_current_g13(session: Session, agent_id: str) -> PolicyEvaluationCore:
    """Evaluate the binding recent trajectory without persisting or mutating it."""
    observations = [
        item for item in build_o_agent_stream(session, agent_id)
        if item.facts.autonomy_run_state != "SKIPPED"
    ]
    recovery_event = latest_operator_recovery(session, agent_id)
    recovery_payload = None
    policy_version = None
    if recovery_event is not None:
        recovery_payload = {**recovery_event.metadata_, "recovery_event_id": recovery_event.event_id}
        cutoff = recovery_event.created_at
        if cutoff.tzinfo is None or cutoff.utcoffset() is None:
            cutoff = cutoff.replace(tzinfo=timezone.utc)
        observations = [
            item for item in observations
            if item.observed_at is not None
            and datetime.fromisoformat(item.observed_at.replace("Z", "+00:00")) > cutoff
            and item.source_id != recovery_event.event_id
        ]
        policy_version = G13_OPERATOR_RECOVERY_POLICY_VERSION
    grouped: dict[str, list[Any]] = {}
    for item in observations:
        run_ids = tuple(item.source_lineage.autonomy_run_ids)
        unit_id = run_ids[0] if run_ids else item.observation_id
        grouped.setdefault(unit_id, []).append(item)
    significant_units: list[str] = []
    for unit_id, items in grouped.items():
        statuses = {
            status
            for item in items
            for status in item.facts.telegraph_statuses
        }
        if "NOT_EXECUTED" in statuses and not statuses - {"NOT_EXECUTED", "REQUESTED"}:
            continue
        significant_units.append(unit_id)
    selected = set(significant_units[-G13_ENFORCEMENT_WINDOW_SIZE:])
    observations = [
        item for item in observations
        if (tuple(item.source_lineage.autonomy_run_ids)[0] if item.source_lineage.autonomy_run_ids else item.observation_id) in selected
    ]
    input_kwargs = {}
    if policy_version is not None:
        input_kwargs = {
            "policy_version": policy_version,
            "operator_recovery": recovery_payload,
        }
    longitudinal_input = G13PolicyInput.from_observations(
        agent_id,
        observations,
        trajectory_lineage_id=f"o-agent-v0:{agent_id}",
        allow_sparse_window=True,
        expected_current_missing_codes=G13_PRE_ACTION_EXPECTED_MISSING,
        **input_kwargs,
    )
    return evaluate_g13_policy(longitudinal_input)


def _latest_epistemic_evaluation(session: Session, mandate_id: str) -> EpistemicEvaluation | None:
    return (
        session.query(EpistemicEvaluation)
        .filter_by(mandate_id=mandate_id)
        .order_by(EpistemicEvaluation.created_at.desc(), EpistemicEvaluation.evaluation_id.desc())
        .first()
    )


def _g12_input_hash(mandate_id: str, reservation: Any | None, authorized: bool) -> str:
    material = {
        "contract": "g12-reservation-eligibility-v0.1",
        "mandate_id": mandate_id,
        "authorized": authorized,
        "reservation": None,
    }
    if reservation is not None:
        material["reservation"] = {
            "mandate_id": reservation.mandate_id,
            "spend_date": reservation.spend_date.isoformat(),
            "reserved_usdc": str(reservation.reserved_usdc),
            "status": reservation.status,
            "origin": reservation.origin,
        }
    return canonical_hash(material)


def run_pre_next_action_authority_check(
    session: Session,
    *,
    mandate: Mandate,
    acquisition: AcquisitionTask,
    run: AutonomyRun,
    g12_authorized: bool,
    g12_reservation: Any | None = None,
    current_runtime_action: str = "CONTINUE_TO_GATEWAY",
    throttled_constraints_satisfied: bool = False,
    enforce: bool = False,
    longitudinal_core: PolicyEvaluationCore | None = None,
) -> AuthorityShadowCheckpoint:
    """Evaluate and persist CD/G12/G13 composition at the action boundary.

    This function is deliberately called after durable G12 reservation
    verification and before the external Gateway request.  ``enforce=True``
    marks the checkpoint as binding; callers must stop before network I/O when
    the composed result is ``RESTRICT``.  The default remains diagnostic for
    existing observation paths.
    """

    agent_id = run.agent_identity_id or mandate.agent_identity_id
    if not agent_id:
        raise ValueError("AUTHORITY_AGENT_IDENTITY_MISSING")

    epistemic_row = _latest_epistemic_evaluation(session, mandate.mandate_id)
    epistemic_core: PolicyEvaluationCore | None = None
    if epistemic_row is not None:
        epistemic_core = evaluate_epistemic_policy(EpistemicPolicyInput.from_evaluation(epistemic_row))
        persist_policy_evaluation(session, epistemic_core)
        epistemic_result = epistemic_core.result
        epistemic_applicability = "APPLICABLE"
        epistemic_id = epistemic_core.policy_evaluation_id
        epistemic_hash = epistemic_core.result_hash
    else:
        # Evidence acquisition precedes the first E1 decision.  CD is therefore
        # explicitly not applicable at this boundary; G12 and binding G13
        # remain fully authoritative for the external acquisition action.
        epistemic_result = "PERMIT"
        epistemic_applicability = "NOT_APPLICABLE"
        epistemic_id = None
        epistemic_hash = None

    # G13 remains longitudinal while allowing documented recovery. Skipped
    # scheduler ticks contain no execution trajectory, so they cannot become
    # permanent negative evidence. A bounded recent window prevents failures
    # from becoming an irreversible lifetime ban; original sequence numbers
    # and hashes remain in the policy input for replay.
    longitudinal_core = longitudinal_core or evaluate_current_g13(session, agent_id)
    persist_policy_evaluation(session, longitudinal_core)
    if enforce:
        identity = session.get(AgentIdentity, agent_id)
        if identity is not None:
            identity.autonomy_state = {
                "CONTINUE": "ACTIVE",
                "THROTTLE": "THROTTLED",
                "REVIEW": "REVIEW_REQUIRED",
                "HALT": "HALTED",
            }[longitudinal_core.result]

    composition_input = AuthorityCompositionInput(
        agent_id=agent_id,
        run_id=run.run_id,
        action_id=acquisition.acquisition_id,
        action_kind="TELEGRAPH_HTTP_ACQUISITION",
        applicability={
            "CD": epistemic_applicability,
            "G12": "APPLICABLE",
            "CDG": "APPLICABLE",
        },
        epistemic_result=epistemic_result,
        epistemic_evaluation_id=epistemic_id,
        epistemic_result_hash=epistemic_hash,
        g12_result="PERMIT" if g12_authorized else "DENY",
        g12_input_hash=_g12_input_hash(mandate.mandate_id, g12_reservation, g12_authorized),
        longitudinal_result=longitudinal_core.result,
        longitudinal_evaluation_id=longitudinal_core.policy_evaluation_id,
        longitudinal_result_hash=longitudinal_core.result_hash,
        throttled_constraints_satisfied=throttled_constraints_satisfied,
        current_runtime_action=current_runtime_action,
        shadow_mode=not enforce,
    )
    composition_core = evaluate_authority_composition(composition_input)
    persist_policy_evaluation(session, composition_core)
    logger.info(
        "PRE_NEXT_ACTION_AUTHORITY_CHECK checkpoint=1 run_id=%s action_id=%s cd=%s g12=%s cdg=%s composed=%s applicability=%s replay_identity=%s shadow_divergence=%s",
        run.run_id,
        acquisition.acquisition_id,
        epistemic_result,
        composition_input.g12_result,
        longitudinal_core.result,
        composition_core.result,
        dict(sorted(composition_input.applicability.items())),
        composition_core.replay_identity,
        composition_core.result_core.get("shadow_divergence"),
    )
    return AuthorityShadowCheckpoint(
        epistemic=epistemic_core,
        longitudinal=longitudinal_core,
        composition=composition_core,
    )


__all__ = [
    "AuthorityShadowCheckpoint",
    "RUNTIME_CHECKPOINT_VERSION",
    "evaluate_current_g13",
    "run_pre_next_action_authority_check",
]


# Descriptive checkpoints use independent transactions and explicit failure records.
VERSION = "authority-shadow-checkpoint-v0.1"


def checkpoint(mandate_id, family, phase, action_id, result, details, refs=()):
    return PolicyEvaluationCore(
        policy_id="AUTHORITY_SHADOW_"+family,
        policy_version=VERSION,
        policy_type="AUTHORITY_CHECKPOINT",
        policy_subject_type="MANDATE",
        policy_subject_id=mandate_id,
        observation_refs=tuple(refs),
        observation_contract_versions={"checkpoint":VERSION},
        input_core={"mandate_id":mandate_id,"family":family,"phase":phase,"action_id":action_id,"details":details},
        triggered_rule_ids=("OBSERVE_PERSISTED_AUTHORITY" if result not in {"UNAVAILABLE","NOT_APPLICABLE"} else result,),
        result=result,
        result_core={"family":family,"observed_result":result,"enforcement":"SHADOW_ONLY","details":details},
    )


def _observe(session, mandate_id, family, phase, acquisition_id):
    mandate = session.get(Mandate,mandate_id)
    if mandate is None: raise ValueError("MANDATE_MISSING")
    refs = []
    details = {}
    if family == "COMPOSITION":
        if mandate.origin != "AUTONOMOUS":
            return None
        run = session.query(AutonomyRun).filter_by(mandate_id=mandate_id).one_or_none()
        acquisition = session.get(AcquisitionTask, acquisition_id)
        reservation = session.get(PublicManualSpendReservation, mandate_id)
        if run is None or acquisition is None or reservation is None:
            raise ValueError("COMPOSITION_INPUT_MISSING")
        composed = run_pre_next_action_authority_check(
            session, mandate=mandate, acquisition=acquisition, run=run,
            g12_authorized=True, g12_reservation=reservation,
        )
        return composed.composition.policy_evaluation_id
    elif family == "CD":
        e1 = session.query(EpistemicEvaluation).filter_by(mandate_id=mandate_id).order_by(EpistemicEvaluation.created_at.desc(),EpistemicEvaluation.evaluation_id.desc()).first()
        decision = session.query(Decision).filter_by(mandate_id=mandate_id).first()
        if e1 is not None:
            from app.authority.epistemic import EpistemicPolicyInput,evaluate_epistemic_policy
            core = evaluate_epistemic_policy(EpistemicPolicyInput.from_evaluation(e1))
            persist_policy_evaluation(session,core)
            refs.append(core.policy_evaluation_id)
            details.update(typed_e1_evaluation_id=e1.evaluation_id,typed_policy_result=core.result)
        details['typed_e1_available'] = e1 is not None
        if decision:
            refs += [decision.decision_id,decision.evaluation_id]
            result = decision.state
            details.update(source='PERSISTED_DECISION',policy_version=decision.policy_version,evidence_set_hash=decision.evidence_set_hash)
        else:
            result = 'UNAVAILABLE'
            details.update(reason='PERSISTED_DECISION_MISSING',absence_imputed=False)
    elif family == "G12":
        reservation = session.get(PublicManualSpendReservation,mandate_id)
        if reservation is None:
            result='UNAVAILABLE';details={'reason':'RESERVATION_MISSING'}
        else:
            result=reservation.status
            details={"spend_date":reservation.spend_date.isoformat(),"reserved_usdc":str(reservation.reserved_usdc),"actual_spend_usdc":str(reservation.actual_spend_usdc) if reservation.actual_spend_usdc is not None else None,"origin":reservation.origin,"authority":"EXISTING_G12_ENFORCED","authorization_recomputed":False}
            refs=[mandate_id]
    else:
        run = session.query(AutonomyRun).filter_by(mandate_id=mandate_id).one_or_none()
        if run is None:
            result='NOT_APPLICABLE';details={'reason':'NO_AUTONOMY_RUN'}
        else:
            agent = run.agent_identity_id or mandate.agent_identity_id
            if not agent: raise ValueError('AUTONOMY_AGENT_IDENTITY_MISSING')
            from app.agents.observation import build_o_agent_stream
            from app.authority.autonomy import G13PolicyInput,evaluate_g13_policy
            observations=build_o_agent_stream(session,agent,run_id=run.run_id)
            # Preserve the observer's canonical ordering and complete sequence.
            core=evaluate_g13_policy(G13PolicyInput.from_observations(agent,observations,trajectory_lineage_id=f'o-agent-v0:{agent}:run:{run.run_id}'))
            persist_policy_evaluation(session,core)
            result=core.result;refs=[run.run_id,core.policy_evaluation_id]
            details={'run_id':run.run_id,'agent_id':agent,'policy_version':core.policy_version,'policy_result_hash':core.result_hash}
    core=checkpoint(mandate_id,family,phase,acquisition_id,result,details,refs)
    persist_policy_evaluation(session,core)
    return core.policy_evaluation_id


def observe_authority_shadow(mandate_id, *, phase, acquisition_id=None, g12_verified=False):
    """Own transactions; neither policy results nor exceptions affect payment.

    An unavailable checkpoint is retried as a diagnostic PolicyEvaluation.
    If PostgreSQL itself is unavailable, persistence is impossible: emit a
    sanitized log and retain that operational limitation, never fabricate a row.
    g12_verified is supplied only by the worker after actual reservation checks;
    a persisted reservation alone is not treated as payment authorization.
    """
    identities=[]
    families = ['CD', 'G12', 'CDG']
    if phase == 'PRE_ACQUISITION' and g12_verified:
        families.append('COMPOSITION')
    for family in families:
        session=None
        try:
            session=SessionLocal()
            session.execute(text("SET LOCAL statement_timeout = '2000ms'"))
            identity = _observe(session,mandate_id,family,phase,acquisition_id)
            if identity is not None:
                identities.append(identity)
            session.commit()
        except Exception as error:
            if session is not None:
                try: session.rollback()
                except Exception: pass
            logger.warning('AUTHORITY_SHADOW_UNAVAILABLE mandate_id=%s family=%s error=%s',mandate_id,family,type(error).__name__)
            fallback=None
            try:
                fallback=SessionLocal()
                fallback.execute(text("SET LOCAL statement_timeout = '2000ms'"))
                core=checkpoint(mandate_id,family,phase,acquisition_id,'UNAVAILABLE',{'reason':'CHECKPOINT_FAILED','error_class':type(error).__name__})
                persist_policy_evaluation(fallback,core)
                fallback.commit()
                identities.append(core.policy_evaluation_id)
            except Exception:
                if fallback is not None:
                    try: fallback.rollback()
                    except Exception: pass
                logger.error('AUTHORITY_SHADOW_UNAVAILABLE_NOT_PERSISTED mandate_id=%s family=%s',mandate_id,family)
            finally:
                if fallback is not None:
                    try: fallback.close()
                    except Exception: pass
        finally:
            if session is not None:
                try: session.close()
                except Exception: pass
    return identities
