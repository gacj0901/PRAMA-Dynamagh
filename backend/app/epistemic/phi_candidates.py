"""Pure pre-kernel O_EPISTEMIC transformation candidates.

The functions in this module operate only on canonical E1/E2-B relational
surfaces.  They have no persistence, network, Decision, autonomy or PRAMA
dependency and deliberately do not define an omega adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from collections.abc import Callable, Iterable, Mapping, Sequence
from decimal import Decimal
import math
from typing import Any, TypeAlias

from app.epistemic.contracts import canonical_json


RELATION_STATES = ("SATISFIES", "CONTRADICTS", "UNRESOLVED", "NOT_APPLICABLE")
SemanticRelation: TypeAlias = tuple[str, str, str, str, str, str]
TurnoverInput: TypeAlias = Fraction | int | float | Decimal
Turnover: TypeAlias = Fraction


def _require_string(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def canonical_relation_element(
    relation: Mapping[str, Any],
    *,
    target_id: str | None = None,
    requirement_id: str | None = None,
    requirement_type: str | None = None,
) -> SemanticRelation:
    """Return the frozen semantic relation element.

    Generated relation UUIDs are intentionally excluded.  Evidence IDs remain
    part of the element because E1 observes attributable artifacts, not merely
    equal typed content.
    """

    resolved_target = relation.get("target_id", target_id)
    resolved_requirement = relation.get("requirement_id", requirement_id)
    resolved_type = relation.get("requirement_type", requirement_type)
    resolved_evidence = relation.get("evidence_id")
    resolved_state = relation.get("relation_state")
    basis = relation.get("relation_basis")
    if not isinstance(basis, Mapping) or not basis:
        raise ValueError("relation_basis must be a non-empty mapping")
    if resolved_state not in RELATION_STATES:
        raise ValueError(f"unsupported relation state: {resolved_state!r}")
    return (
        _require_string("target_id", resolved_target),
        _require_string("requirement_id", resolved_requirement),
        _require_string("requirement_type", resolved_type),
        _require_string("evidence_id", resolved_evidence),
        resolved_state,
        canonical_json(dict(basis)).decode("utf-8"),
    )


def canonical_relation_set(
    relations: Iterable[Mapping[str, Any]],
    *,
    target_id: str,
    requirement_id: str,
    requirement_type: str,
) -> frozenset[SemanticRelation]:
    """Build a requirement-local canonical semantic relation set."""

    result = frozenset(
        canonical_relation_element(
            relation,
            target_id=target_id,
            requirement_id=requirement_id,
            requirement_type=requirement_type,
        )
        for relation in relations
    )
    if any(item[0] != target_id or item[1] != requirement_id for item in result):
        raise ValueError("relation set crosses the declared requirement scope")
    return result


def _canonical_set(value: Iterable[SemanticRelation]) -> frozenset[SemanticRelation]:
    result = frozenset(value)
    for item in result:
        if not isinstance(item, tuple) or len(item) != 6 or not all(isinstance(part, str) for part in item):
            raise ValueError("invalid canonical semantic relation element")
        if item[4] not in RELATION_STATES:
            raise ValueError(f"unsupported relation state: {item[4]!r}")
    return result


def relational_loss(
    previous: Iterable[SemanticRelation], current: Iterable[SemanticRelation]
) -> tuple[SemanticRelation, ...]:
    """Return the deterministic semantic relation loss set."""

    return tuple(sorted(_canonical_set(previous) - _canonical_set(current)))


def relational_gain(
    previous: Iterable[SemanticRelation], current: Iterable[SemanticRelation]
) -> tuple[SemanticRelation, ...]:
    """Return the deterministic semantic relation gain set."""

    return tuple(sorted(_canonical_set(current) - _canonical_set(previous)))


def relational_set_distance(
    previous: Iterable[SemanticRelation], current: Iterable[SemanticRelation]
) -> Fraction:
    """Return the candidate symmetric-difference turnover measure.

    The union cardinality is the natural reference for fractional turnover of
    a canonical set.  Fraction keeps the pure candidate exact and deterministic.
    """

    previous_set = _canonical_set(previous)
    current_set = _canonical_set(current)
    union = previous_set | current_set
    if not union:
        return Fraction(0, 1)
    return Fraction(len(previous_set ^ current_set), len(union))


def _canonical_turnover(value: TurnoverInput) -> Turnover:
    """Convert a candidate turnover to an exact, bounded Fraction.

    Floats are converted through their decimal spelling so fixture values such
    as ``0.1`` retain their declared deterministic meaning.  ``None`` is not a
    valid observed turnover; unavailable expectations are represented by the
    return value ``None`` below and are never replaced with zero.
    """

    if isinstance(value, bool):
        raise TypeError("turnover must be numeric, not bool")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("turnover must be finite")
        result = Fraction(str(value))
    elif isinstance(value, (Fraction, int, Decimal)):
        result = Fraction(value)
    else:
        raise TypeError("turnover must be Fraction, int, float, or Decimal")
    if not 0 <= result <= 1:
        raise ValueError("turnover must be in [0, 1]")
    return result


@dataclass(frozen=True)
class CausalExpectationPoint:
    """Identity of an event before its current turnover is observed."""

    trajectory_lineage_id: str
    target_id: str
    requirement_id: str
    requirement_type: str
    semantic_version_tuple: tuple[tuple[str, str], ...]
    event_index: int

    def __post_init__(self) -> None:
        _require_string("trajectory_lineage_id", self.trajectory_lineage_id)
        _require_string("target_id", self.target_id)
        _require_string("requirement_id", self.requirement_id)
        _require_string("requirement_type", self.requirement_type)
        if isinstance(self.event_index, bool) or not isinstance(self.event_index, int) or self.event_index < 0:
            raise ValueError("event_index must be a non-negative integer")
        for name, version in self.semantic_version_tuple:
            _require_string("semantic version name", name)
            _require_string("semantic version", version)

    @classmethod
    def from_observation(cls, observation: "CausalTurnoverObservation") -> "CausalExpectationPoint":
        return cls(
            trajectory_lineage_id=observation.trajectory_lineage_id,
            target_id=observation.target_id,
            requirement_id=observation.requirement_id,
            requirement_type=observation.requirement_type,
            semantic_version_tuple=observation.semantic_version_tuple,
            event_index=observation.event_index,
        )

    def population_key(self) -> tuple[str, str, str, tuple[tuple[str, str], ...]]:
        """Return the frozen P1 causal population identity."""

        return (
            self.trajectory_lineage_id,
            self.target_id,
            self.requirement_id,
            self.semantic_version_tuple,
        )


@dataclass(frozen=True)
class CausalTurnoverObservation(CausalExpectationPoint):
    """One artifact-attributed turnover value in a version-frozen lineage."""

    turnover: TurnoverInput

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "turnover", _canonical_turnover(self.turnover))


def _prior_turnovers(
    history: Sequence[CausalTurnoverObservation],
    current: CausalExpectationPoint,
) -> tuple[Turnover, ...]:
    """Return only the strict P1 prefix, independent of input order."""

    matching = [
        item
        for item in history
        if item.population_key() == current.population_key()
        and item.event_index < current.event_index
    ]
    if any(item.requirement_type != current.requirement_type for item in matching):
        raise ValueError("requirement type changed within a causal population")

    prior = sorted(
        (item.event_index, item.turnover)
        for item in matching
    )
    for (left_index, _), (right_index, _) in zip(prior, prior[1:], strict=False):
        if left_index == right_index:
            raise ValueError("duplicate event_index within a causal population")
    return tuple(value for _, value in prior)


def previous_value_expectation(
    history: Sequence[CausalTurnoverObservation],
    current: CausalExpectationPoint,
) -> Turnover | None:
    """Return the strictly causal PV baseline, or ``None`` during warm-up."""

    prior = _prior_turnovers(history, current)
    return prior[-1] if prior else None


def expanding_causal_mean_expectation(
    history: Sequence[CausalTurnoverObservation],
    current: CausalExpectationPoint,
) -> Turnover | None:
    """Return the strictly causal ECM baseline, or ``None`` during warm-up."""

    prior = _prior_turnovers(history, current)
    if not prior:
        return None
    return sum(prior, Fraction(0, 1)) / len(prior)


ExpectationEstimator: TypeAlias = Callable[
    [Sequence[CausalTurnoverObservation], CausalExpectationPoint], Turnover | None
]


def causal_expectation_stream(
    observations: Sequence[CausalTurnoverObservation],
    estimator: ExpectationEstimator,
) -> tuple[Turnover | None, ...]:
    """Build a deterministic expectation stream without observing current d."""

    ordered = tuple(
        sorted(
            observations,
            key=lambda item: (item.population_key(), item.event_index, item.turnover),
        )
    )
    return tuple(
        estimator(ordered, CausalExpectationPoint.from_observation(item))
        for item in ordered
    )


def change_occurrence(
    previous: Iterable[SemanticRelation], current: Iterable[SemanticRelation]
) -> bool:
    """Return the categorical change/no-change candidate."""

    return _canonical_set(previous) != _canonical_set(current)


def typed_relational_delta(
    previous: Iterable[SemanticRelation], current: Iterable[SemanticRelation]
) -> dict[str, Any]:
    """Partition the primitive delta without assigning weights."""

    previous_set = _canonical_set(previous)
    current_set = _canonical_set(current)
    added = current_set - previous_set
    removed = previous_set - current_set

    added_by_state = {
        state: tuple(sorted(item for item in added if item[4] == state))
        for state in RELATION_STATES
    }
    removed_by_state = {
        state: tuple(sorted(item for item in removed if item[4] == state))
        for state in RELATION_STATES
    }

    previous_by_core: dict[tuple[str, str, str, str], list[SemanticRelation]] = {}
    current_by_core: dict[tuple[str, str, str, str], list[SemanticRelation]] = {}
    for item in previous_set:
        previous_by_core.setdefault(item[:4], []).append(item)
    for item in current_set:
        current_by_core.setdefault(item[:4], []).append(item)

    changed_basis: list[dict[str, SemanticRelation | str]] = []
    for core in sorted(set(previous_by_core) & set(current_by_core)):
        old_items = previous_by_core[core]
        new_items = current_by_core[core]
        if len(old_items) == 1 and len(new_items) == 1 and old_items[0] != new_items[0]:
            changed_basis.append(
                {
                    "previous_state": old_items[0][4],
                    "current_state": new_items[0][4],
                    "previous": old_items[0],
                    "current": new_items[0],
                }
            )

    return {
        "added_by_state": added_by_state,
        "removed_by_state": removed_by_state,
        "changed_basis_by_state": tuple(changed_basis),
    }


@dataclass(frozen=True)
class RelationSetPoint:
    """Minimal fixture point for the categorical restoration candidate."""

    trajectory_lineage_id: str
    event_index: int
    semantic_version_tuple: tuple[tuple[str, str], ...]
    relations: frozenset[SemanticRelation]

    def __post_init__(self) -> None:
        _require_string("trajectory_lineage_id", self.trajectory_lineage_id)
        if isinstance(self.event_index, bool) or not isinstance(self.event_index, int) or self.event_index < 0:
            raise ValueError("event_index must be a non-negative integer")
        for name, version in self.semantic_version_tuple:
            _require_string("semantic version name", name)
            _require_string("semantic version", version)
        _canonical_set(self.relations)


def relational_restoration(
    history: Sequence[RelationSetPoint], current: RelationSetPoint
) -> bool:
    """Detect restoration from the prior same-lineage prefix only."""

    if not history:
        return False
    previous_index = -1
    for point in history:
        if point.trajectory_lineage_id != current.trajectory_lineage_id:
            raise ValueError("restoration history crosses trajectory lineages")
        if point.semantic_version_tuple != current.semantic_version_tuple:
            raise ValueError("restoration history crosses semantic versions")
        if point.event_index <= previous_index:
            raise ValueError("restoration history is not strictly ordered")
        previous_index = point.event_index
    if current.event_index != previous_index + 1:
        raise ValueError("current event is not the next causal event")
    if history[-1].relations == current.relations:
        return False
    return any(
        point.relations == current.relations
        and any(prior.relations != current.relations for prior in history[index + 1 :])
        for index, point in enumerate(history)
    )
