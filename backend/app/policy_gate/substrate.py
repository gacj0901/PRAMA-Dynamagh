"""Deterministic, typed policy-gate substrate.

Only mechanics genuinely common to the two authorities live here. Domain
rules and input schemas remain in the epistemic and autonomy specializations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import uuid
from typing import Any, Callable, Mapping

from sqlalchemy.exc import IntegrityError

from app.epistemic.contracts import canonical_hash


POLICY_GATE_SUBSTRATE_VERSION = "policy-gate-substrate-v0.1"
POLICY_TYPES = frozenset({"EPISTEMIC_DECISION", "STRUCTURAL_AUTONOMY", "AUTHORITY_CHECKPOINT"})


class PolicyInputTypeError(ValueError):
    """Raised when a specialization receives the other policy's input."""


def _sorted_strings(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(sorted({str(value) for value in values}))


@dataclass(frozen=True)
class PolicyEvaluationCore:
    """Immutable deterministic policy result.

    ``created_at`` is audit metadata and is intentionally excluded from all
    canonical material. ``input_core`` and ``result_core`` are owned by the
    specialized policy and are never interpreted by this substrate.
    """

    policy_id: str
    policy_version: str
    policy_type: str
    policy_subject_type: str
    policy_subject_id: str
    observation_refs: tuple[str, ...]
    observation_contract_versions: Mapping[str, str]
    input_core: Mapping[str, Any]
    triggered_rule_ids: tuple[str, ...]
    result: str
    result_core: Mapping[str, Any]
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.policy_type not in POLICY_TYPES:
            raise PolicyInputTypeError("POLICY_TYPE_UNSUPPORTED")
        for name in (
            "policy_id",
            "policy_version",
            "policy_subject_type",
            "policy_subject_id",
            "result",
        ):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ValueError(f"{name} must be non-empty")
        if not isinstance(self.input_core, Mapping) or not self.input_core:
            raise ValueError("input_core is required")
        if not isinstance(self.result_core, Mapping) or not self.result_core:
            raise ValueError("result_core is required")
        if self.created_at is not None and (self.created_at.tzinfo is None or self.created_at.utcoffset() is None):
            raise ValueError("created_at must be timezone-aware")

    @property
    def canonical_input(self) -> dict[str, Any]:
        return {
            "policy_gate_substrate_version": POLICY_GATE_SUBSTRATE_VERSION,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_type": self.policy_type,
            "policy_subject_type": self.policy_subject_type,
            "policy_subject_id": self.policy_subject_id,
            "observation_refs": list(self.observation_refs),
            "observation_contract_versions": dict(sorted(self.observation_contract_versions.items())),
            "input_core": dict(self.input_core),
        }

    @property
    def input_hash(self) -> str:
        return canonical_hash(self.canonical_input)

    @property
    def canonical_result(self) -> dict[str, Any]:
        return {
            "policy_gate_substrate_version": POLICY_GATE_SUBSTRATE_VERSION,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_type": self.policy_type,
            "triggered_rule_ids": list(_sorted_strings(self.triggered_rule_ids)),
            "result": self.result,
            "result_core": dict(self.result_core),
        }

    @property
    def result_hash(self) -> str:
        return canonical_hash(self.canonical_result)

    @property
    def replay_identity(self) -> str:
        return canonical_hash(
            {
                "policy_id": self.policy_id,
                "policy_version": self.policy_version,
                "policy_type": self.policy_type,
                "policy_subject_type": self.policy_subject_type,
                "policy_subject_id": self.policy_subject_id,
                "input_hash": self.input_hash,
            }
        )

    @property
    def policy_evaluation_id(self) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"prama-dynamagh:policy-evaluation:{self.replay_identity}"))

    def orm_values(self) -> dict[str, Any]:
        return {
            "policy_evaluation_id": self.policy_evaluation_id,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_type": self.policy_type,
            "policy_subject_type": self.policy_subject_type,
            "policy_subject_id": self.policy_subject_id,
            "observation_refs": list(self.observation_refs),
            "observation_contract_versions": dict(self.observation_contract_versions),
            "input_core": dict(self.input_core),
            "input_hash": self.input_hash,
            "triggered_rule_ids": list(_sorted_strings(self.triggered_rule_ids)),
            "result": self.result,
            "result_core": dict(self.result_core),
            "result_hash": self.result_hash,
            "replay_identity": self.replay_identity,
            "created_at": self.created_at or datetime.now(timezone.utc),
        }


def persist_policy_evaluation(session: Any, evaluation: PolicyEvaluationCore) -> Any:
    """Insert once, or return the exact existing deterministic result."""

    from app.domain.mandates import PolicyEvaluation

    existing = session.get(PolicyEvaluation, evaluation.policy_evaluation_id)
    if existing is not None:
        if existing.input_hash != evaluation.input_hash or existing.result_hash != evaluation.result_hash:
            raise ValueError("POLICY_EVALUATION_ID_CONFLICT")
        return existing
    row = PolicyEvaluation(**evaluation.orm_values())
    session.add(row)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        existing = session.query(PolicyEvaluation).filter_by(replay_identity=evaluation.replay_identity).one_or_none()
        if existing is None:
            raise
        if existing.input_hash != evaluation.input_hash or existing.result_hash != evaluation.result_hash:
            raise ValueError("POLICY_EVALUATION_ID_CONFLICT")
        return existing
    return row


def assert_policy_input_type(evaluation: PolicyEvaluationCore, expected: str) -> None:
    if evaluation.policy_type != expected:
        raise PolicyInputTypeError("POLICY_INPUT_TYPE_MISMATCH")


def replay_policy(
    persisted: PolicyEvaluationCore,
    recompute: Callable[[], PolicyEvaluationCore],
) -> PolicyEvaluationCore:
    """Replay one specialization through the shared exactness check."""

    replayed = recompute()
    if (
        replayed.policy_id != persisted.policy_id
        or replayed.policy_version != persisted.policy_version
        or replayed.policy_type != persisted.policy_type
        or replayed.policy_subject_type != persisted.policy_subject_type
        or replayed.policy_subject_id != persisted.policy_subject_id
        or replayed.input_hash != persisted.input_hash
        or replayed.result_hash != persisted.result_hash
        or tuple(sorted(replayed.triggered_rule_ids)) != tuple(sorted(persisted.triggered_rule_ids))
        or replayed.result != persisted.result
    ):
        raise ValueError("POLICY_REPLAY_MISMATCH")
    return replayed
