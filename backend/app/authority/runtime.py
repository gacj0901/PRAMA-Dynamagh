"""Shadow-only authority checkpoint for the autonomous execution boundary."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.agents.observation import build_o_agent_stream
from app.authority.autonomy import G13PolicyInput, evaluate_g13_policy
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
)
from app.epistemic.contracts import canonical_hash
from app.policy_gate.substrate import PolicyEvaluationCore, persist_policy_evaluation


logger = logging.getLogger(__name__)
RUNTIME_CHECKPOINT_VERSION = "pre-next-action-authority-check-v0.1"


@dataclass(frozen=True)
class AuthorityShadowCheckpoint:
    epistemic: PolicyEvaluationCore | None
    longitudinal: PolicyEvaluationCore
    composition: PolicyEvaluationCore


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
) -> AuthorityShadowCheckpoint:
    """Evaluate and persist CD/G12/CDG composition without enforcement.

    This function is deliberately called after durable G12 reservation
    verification and before the external Gateway request.  It writes only the
    existing append-only policy substrate; its result is never used to block
    the caller in this shadow gate.
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
        # No E1 snapshot exists before a first acquisition.  Preserve the
        # existing fail-closed CD semantics explicitly rather than permitting.
        epistemic_result = "REVIEW"
        epistemic_applicability = "MISSING"
        epistemic_id = None
        epistemic_hash = None

    observations = build_o_agent_stream(session, agent_id, run_id=run.run_id)
    trajectory = [item for item in observations if item.source_kind != "AGENT_IDENTITY"]
    longitudinal_input = G13PolicyInput.from_observations(
        agent_id,
        trajectory,
        trajectory_lineage_id=f"o-agent-v0:{agent_id}",
    )
    longitudinal_core = evaluate_g13_policy(longitudinal_input)
    persist_policy_evaluation(session, longitudinal_core)

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
        shadow_mode=True,
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
    "run_pre_next_action_authority_check",
]
