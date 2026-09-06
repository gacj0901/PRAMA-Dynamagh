"""E2-B categorical epistemic trajectory contract.

This module is an offline, non-persisted transition derivation layer over the
immutable E1 relational snapshots.  It deliberately does not define ``omega``
and does not import or invoke PRAMA.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from collections.abc import Iterable, Mapping
import uuid
from typing import Any

from app.epistemic.contracts import canonical_hash, canonical_json


E2_B_OBSERVER_VERSION = "O_EPISTEMIC_E2B-v0.1"
E2_B_CONTRACT_VERSION = "e2-b-categorical-epistemic-trajectory-v0.1"
E2_B_ALGORITHM_VERSION = "e2-b-set-delta-v0.1"
E2_B_CANONICALIZATION_VERSION = "e2-b-canonical-v0.1"

REQUIREMENT_STATES = ("SATISFIED", "UNRESOLVED", "CONTRADICTED")
RELATION_STATES = ("SATISFIES", "CONTRADICTS", "UNRESOLVED", "NOT_APPLICABLE")
STRUCTURAL_STATES = ("COMPLETE", "INCOMPLETE", "CONTRADICTED")
TRANSITION_KINDS = (
    "EXACT_NO_OP",
    "SAME_STATE_RELATIONAL_CHANGE",
    "STATE_CHANGE",
)


def _value(item: object, name: str) -> Any:
    if isinstance(item, Mapping):
        if name not in item:
            raise ValueError(f"missing E2-B field: {name}")
        return item[name]
    try:
        return getattr(item, name)
    except AttributeError as error:
        raise ValueError(f"missing E2-B field: {name}") from error


def _plain(value: Any) -> Any:
    """Freeze JSON-compatible source data without preserving object identity."""

    return __import__("json").loads(canonical_json(value).decode("utf-8"))


def _require_string(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _require_state(name: str, value: Any, allowed: tuple[str, ...]) -> str:
    if value not in allowed:
        raise ValueError(f"unsupported {name}: {value!r}")
    return value


def _normalize_requirement_state(item: object) -> dict[str, Any]:
    state = {
        "requirement_id": _require_string("requirement_id", _value(item, "requirement_id")),
        "requirement_type": _require_string("requirement_type", _value(item, "requirement_type")),
        "required": _value(item, "required"),
        "state": _require_state("requirement state", _value(item, "state"), REQUIREMENT_STATES),
        "supporting_relation_ids": sorted(str(value) for value in (_value(item, "supporting_relation_ids") or [])),
        "contradicting_relation_ids": sorted(str(value) for value in (_value(item, "contradicting_relation_ids") or [])),
        "unresolved_relation_ids": sorted(str(value) for value in (_value(item, "unresolved_relation_ids") or [])),
        "not_applicable_relation_ids": sorted(str(value) for value in (_value(item, "not_applicable_relation_ids") or [])),
    }
    if not isinstance(state["required"], bool):
        raise ValueError("required must be boolean")
    return state


def _normalize_relation(item: object) -> dict[str, Any]:
    relation_state = _require_state(
        "relation state", _value(item, "relation_state"), RELATION_STATES
    )
    relation_id = _require_string("relation_id", _value(item, "relation_id"))
    evidence_id = _require_string("evidence_id", _value(item, "evidence_id"))
    requirement_id = _require_string("requirement_id", _value(item, "requirement_id"))
    relation_basis = _value(item, "relation_basis")
    if not isinstance(relation_basis, Mapping) or not relation_basis:
        raise ValueError("relation_basis must be a non-empty mapping")
    return {
        "relation_id": relation_id,
        "requirement_id": requirement_id,
        "evidence_id": evidence_id,
        "relation_state": relation_state,
        "relation_basis": _plain(dict(relation_basis)),
    }


@dataclass(frozen=True)
class E1RelationalSnapshot:
    """A normalized, immutable view of one persisted or fixture E1 snapshot."""

    evaluation_id: str
    target_id: str
    requirement_states: tuple[dict[str, Any], ...]
    relations: tuple[dict[str, Any], ...]
    structural_state: str
    observer_version: str
    contract_version: str
    algorithm_version: str

    @classmethod
    def from_evaluation(
        cls,
        evaluation: object,
        *,
        relations: Iterable[object] | None = None,
        evaluation_id: str | None = None,
    ) -> "E1RelationalSnapshot":
        """Adapt an E1 evaluation without adding runtime or persistence behavior."""

        resolved_evaluation_id = evaluation_id or _value(evaluation, "evaluation_id")
        relation_source = (
            list(relations)
            if relations is not None
            else list(_value(evaluation, "relations") or [])
        )
        return cls(
            evaluation_id=_require_string("evaluation_id", resolved_evaluation_id),
            target_id=_require_string("target_id", _value(evaluation, "target_id")),
            requirement_states=tuple(
                _normalize_requirement_state(item)
                for item in (_value(evaluation, "requirement_states") or [])
            ),
            relations=tuple(_normalize_relation(item) for item in relation_source),
            structural_state=_require_state(
                "structural state", _value(evaluation, "structural_state"), STRUCTURAL_STATES
            ),
            observer_version=_require_string(
                "observer_version", _value(evaluation, "observer_version")
            ),
            contract_version=_require_string(
                "contract_version", _value(evaluation, "contract_version")
            ),
            algorithm_version=_require_string(
                "algorithm_version", _value(evaluation, "algorithm_version")
            ),
        )


@dataclass(frozen=True)
class E2BTrajectoryPoint:
    """One fixture-supplied point in an experimental target trajectory."""

    event_index: int
    snapshot: E1RelationalSnapshot

    def __post_init__(self) -> None:
        if isinstance(self.event_index, bool) or not isinstance(self.event_index, int):
            raise ValueError("event_index must be an integer")
        if self.event_index < 0:
            raise ValueError("event_index must be non-negative")


@dataclass(frozen=True)
class EpistemicTransitionObservation:
    """Requirement-level categorical transition; no scalarization is included."""

    transition_id: str
    target_id: str
    requirement_id: str
    requirement_type: str
    event_index: int
    previous_evaluation_id: str
    current_evaluation_id: str
    previous_requirement_state: str
    current_requirement_state: str
    added_relation_ids: tuple[str, ...]
    removed_relation_ids: tuple[str, ...]
    added_supporting_evidence_ids: tuple[str, ...]
    removed_supporting_evidence_ids: tuple[str, ...]
    added_contradicting_evidence_ids: tuple[str, ...]
    removed_contradicting_evidence_ids: tuple[str, ...]
    previous_structural_state: str
    current_structural_state: str
    transition_basis: dict[str, Any]
    contract_version: str
    observer_version: str
    algorithm_version: str
    canonical_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "transition_id": self.transition_id,
            "target_id": self.target_id,
            "requirement_id": self.requirement_id,
            "requirement_type": self.requirement_type,
            "event_index": self.event_index,
            "previous_evaluation_id": self.previous_evaluation_id,
            "current_evaluation_id": self.current_evaluation_id,
            "previous_requirement_state": self.previous_requirement_state,
            "current_requirement_state": self.current_requirement_state,
            "added_relation_ids": list(self.added_relation_ids),
            "removed_relation_ids": list(self.removed_relation_ids),
            "added_supporting_evidence_ids": list(self.added_supporting_evidence_ids),
            "removed_supporting_evidence_ids": list(self.removed_supporting_evidence_ids),
            "added_contradicting_evidence_ids": list(self.added_contradicting_evidence_ids),
            "removed_contradicting_evidence_ids": list(self.removed_contradicting_evidence_ids),
            "previous_structural_state": self.previous_structural_state,
            "current_structural_state": self.current_structural_state,
            "transition_basis": self.transition_basis,
            "contract_version": self.contract_version,
            "observer_version": self.observer_version,
            "algorithm_version": self.algorithm_version,
            "canonical_hash": self.canonical_hash,
        }


def _requirement_map(snapshot: E1RelationalSnapshot) -> dict[str, dict[str, Any]]:
    result = {}
    for item in snapshot.requirement_states:
        requirement_id = item["requirement_id"]
        if requirement_id in result:
            raise ValueError("duplicate requirement_id in E1 snapshot")
        result[requirement_id] = item
    return result


def _relation_map(snapshot: E1RelationalSnapshot) -> dict[str, dict[str, Any]]:
    result = {}
    for item in snapshot.relations:
        relation_id = item["relation_id"]
        if relation_id in result:
            raise ValueError("duplicate relation_id in E1 snapshot")
        result[relation_id] = item
    return result


def _relation_semantics(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "relation_id": item["relation_id"],
        "requirement_id": item["requirement_id"],
        "evidence_id": item["evidence_id"],
        "relation_state": item["relation_state"],
        "relation_basis": item["relation_basis"],
    }


def _relation_signature(item: Mapping[str, Any]) -> str:
    return canonical_json(_relation_semantics(item)).decode("utf-8")


def _evidence_for_state(
    relations: Mapping[str, Mapping[str, Any]],
    relation_state: str,
    requirement_id: str,
) -> set[str]:
    return {
        item["evidence_id"]
        for item in relations.values()
        if item["requirement_id"] == requirement_id and item["relation_state"] == relation_state
    }


def _canonical_body(observation: EpistemicTransitionObservation) -> dict[str, Any]:
    """Return only semantic transition content; incidental IDs are excluded."""

    return {
        "canonicalization_version": E2_B_CANONICALIZATION_VERSION,
        "target_id": observation.target_id,
        "requirement_id": observation.requirement_id,
        "requirement_type": observation.requirement_type,
        "event_index": observation.event_index,
        "previous_requirement_state": observation.previous_requirement_state,
        "current_requirement_state": observation.current_requirement_state,
        "added_relation_ids": list(observation.added_relation_ids),
        "removed_relation_ids": list(observation.removed_relation_ids),
        "added_supporting_evidence_ids": list(observation.added_supporting_evidence_ids),
        "removed_supporting_evidence_ids": list(observation.removed_supporting_evidence_ids),
        "added_contradicting_evidence_ids": list(observation.added_contradicting_evidence_ids),
        "removed_contradicting_evidence_ids": list(observation.removed_contradicting_evidence_ids),
        "previous_structural_state": observation.previous_structural_state,
        "current_structural_state": observation.current_structural_state,
        "transition_basis": observation.transition_basis,
        "contract_version": observation.contract_version,
        "observer_version": observation.observer_version,
        "algorithm_version": observation.algorithm_version,
    }


def derive_transition(
    previous: E1RelationalSnapshot,
    current: E1RelationalSnapshot,
    *,
    previous_event_index: int,
    event_index: int,
    requirement_id: str,
    transition_id: str | None = None,
) -> EpistemicTransitionObservation:
    """Derive one deterministic requirement-level set delta."""

    if isinstance(previous_event_index, bool) or not isinstance(previous_event_index, int):
        raise ValueError("previous_event_index must be an integer")
    if isinstance(event_index, bool) or not isinstance(event_index, int):
        raise ValueError("event_index must be an integer")
    if previous_event_index < 0 or event_index <= previous_event_index:
        raise ValueError("event_index must be strictly increasing")
    if previous.target_id != current.target_id:
        raise ValueError("E2-B transitions cannot cross target trajectories")
    for name in ("observer_version", "contract_version", "algorithm_version"):
        if getattr(previous, name) != getattr(current, name):
            raise ValueError(f"E2-B version mismatch: {name}")

    previous_requirements = _requirement_map(previous)
    current_requirements = _requirement_map(current)
    if set(previous_requirements) != set(current_requirements):
        raise ValueError("E2-B requires stable requirement identity across snapshots")
    if requirement_id not in previous_requirements:
        raise ValueError("requirement_id is absent from E1 snapshots")
    previous_requirement = previous_requirements[requirement_id]
    current_requirement = current_requirements[requirement_id]
    if previous_requirement["requirement_type"] != current_requirement["requirement_type"]:
        raise ValueError("requirement_type cannot change within an E2-B trajectory")

    previous_relations = _relation_map(previous)
    current_relations = _relation_map(current)
    for relation in (*previous_relations.values(), *current_relations.values()):
        if relation["requirement_id"] == requirement_id and relation["requirement_id"] not in previous_requirements:
            raise ValueError("relation references unknown requirement")

    previous_for_requirement = {
        key: value for key, value in previous_relations.items() if value["requirement_id"] == requirement_id
    }
    current_for_requirement = {
        key: value for key, value in current_relations.items() if value["requirement_id"] == requirement_id
    }
    previous_ids = set(previous_for_requirement)
    current_ids = set(current_for_requirement)
    added_relation_ids = tuple(sorted(current_ids - previous_ids))
    removed_relation_ids = tuple(sorted(previous_ids - current_ids))

    changed_relation_ids = sorted(
        relation_id
        for relation_id in previous_ids & current_ids
        if _relation_signature(previous_for_requirement[relation_id])
        != _relation_signature(current_for_requirement[relation_id])
    )
    relation_state_changes = [
        {
            "relation_id": relation_id,
            "previous": _relation_semantics(previous_for_requirement[relation_id]),
            "current": _relation_semantics(current_for_requirement[relation_id]),
        }
        for relation_id in changed_relation_ids
    ]

    previous_support = _evidence_for_state(previous_for_requirement, "SATISFIES", requirement_id)
    current_support = _evidence_for_state(current_for_requirement, "SATISFIES", requirement_id)
    previous_contradictions = _evidence_for_state(previous_for_requirement, "CONTRADICTS", requirement_id)
    current_contradictions = _evidence_for_state(current_for_requirement, "CONTRADICTS", requirement_id)

    added_supporting = tuple(sorted(current_support - previous_support))
    removed_supporting = tuple(sorted(previous_support - current_support))
    added_contradicting = tuple(sorted(current_contradictions - previous_contradictions))
    removed_contradicting = tuple(sorted(previous_contradictions - current_contradictions))

    requirement_changed = previous_requirement["state"] != current_requirement["state"]
    relation_changed = bool(
        added_relation_ids
        or removed_relation_ids
        or changed_relation_ids
        or added_supporting
        or removed_supporting
        or added_contradicting
        or removed_contradicting
    )
    if not requirement_changed and not relation_changed:
        transition_kind = "EXACT_NO_OP"
    elif not requirement_changed:
        transition_kind = "SAME_STATE_RELATIONAL_CHANGE"
    else:
        transition_kind = "STATE_CHANGE"

    transition_basis = {
        "canonicalization_version": E2_B_CANONICALIZATION_VERSION,
        "transition_kind": transition_kind,
        "relation_state_changes": relation_state_changes,
    }
    observation = EpistemicTransitionObservation(
        transition_id=transition_id or str(uuid.uuid4()),
        target_id=current.target_id,
        requirement_id=requirement_id,
        requirement_type=current_requirement["requirement_type"],
        event_index=event_index,
        previous_evaluation_id=previous.evaluation_id,
        current_evaluation_id=current.evaluation_id,
        previous_requirement_state=previous_requirement["state"],
        current_requirement_state=current_requirement["state"],
        added_relation_ids=added_relation_ids,
        removed_relation_ids=removed_relation_ids,
        added_supporting_evidence_ids=added_supporting,
        removed_supporting_evidence_ids=removed_supporting,
        added_contradicting_evidence_ids=added_contradicting,
        removed_contradicting_evidence_ids=removed_contradicting,
        previous_structural_state=previous.structural_state,
        current_structural_state=current.structural_state,
        transition_basis=transition_basis,
        contract_version=current.contract_version,
        observer_version=current.observer_version,
        algorithm_version=current.algorithm_version,
        canonical_hash="",
    )
    return replace(observation, canonical_hash=canonical_hash(_canonical_body(observation)))


def build_transition_stream(
    points: Iterable[E2BTrajectoryPoint],
    *,
    include_exact_noops: bool = False,
) -> tuple[EpistemicTransitionObservation, ...]:
    """Build a deterministic stream in the explicit fixture event order."""

    materialized = list(points)
    if len(materialized) < 2:
        return ()
    target_id = materialized[0].snapshot.target_id
    for previous_point, current_point in zip(materialized, materialized[1:]):
        if current_point.snapshot.target_id != target_id:
            raise ValueError("E2-B stream cannot cross target trajectories")
        if current_point.event_index <= previous_point.event_index:
            raise ValueError("E2-B event_index must be strictly increasing")

    transitions: list[EpistemicTransitionObservation] = []
    for previous_point, current_point in zip(materialized, materialized[1:]):
        previous_requirements = _requirement_map(previous_point.snapshot)
        current_requirements = _requirement_map(current_point.snapshot)
        if set(previous_requirements) != set(current_requirements):
            raise ValueError("E2-B requires stable requirement identity across snapshots")
        for requirement_id in sorted(current_requirements):
            transition = derive_transition(
                previous_point.snapshot,
                current_point.snapshot,
                previous_event_index=previous_point.event_index,
                event_index=current_point.event_index,
                requirement_id=requirement_id,
            )
            if include_exact_noops or transition.transition_basis["transition_kind"] != "EXACT_NO_OP":
                transitions.append(transition)
    return tuple(transitions)


def replay_transition_stream(
    points: Iterable[E2BTrajectoryPoint],
    *,
    include_exact_noops: bool = False,
) -> tuple[EpistemicTransitionObservation, ...]:
    """Replay is a pure reconstruction from the same explicit fixture points."""

    return build_transition_stream(points, include_exact_noops=include_exact_noops)
