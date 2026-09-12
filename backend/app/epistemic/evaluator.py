"""Pure deterministic E1-C2 relational evaluation.

This module consumes only persisted E1 contracts and already-admitted Evidence.
It has no network, acquisition, payment, PRAMA, autonomy, or Decision Gate path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping
import uuid

from app.domain.mandates import (
    EpistemicEvaluation,
    EpistemicTarget,
    Evidence,
    EvidenceRelation,
    EvidenceRequirement,
    CryptoPriceEvidence,
)
from app.epistemic.contracts import (
    CRYPTO_PRICE_EVIDENCE_SCHEMA_VERSION,
    E1_CANONICALIZATION_VERSION,
    canonical_decimal,
    canonical_hash,
    canonical_timestamp,
)
from app.epistemic.registry import lookup as registry_lookup


E1_C2_OBSERVER_VERSION = "O_EPISTEMIC-v0.1"
E1_C2_CONTRACT_VERSION = "e1-c2-crypto-price-v0.1"
E1_C2_ALGORITHM_VERSION = "e1-c2-deterministic-relational-v0.1"
E1_EVIDENCE_SET_HASH_VERSION = "e1-evidence-set-v0.1"
E1_ADMISSION_VERSION = "evidence-admission-v0"
E1_ELIGIBLE_ADMISSION_STATES = ("ADMITTED", "LIMITED")

RELATION_STATES = ("SATISFIES", "CONTRADICTS", "UNRESOLVED", "NOT_APPLICABLE")
STRUCTURAL_STATES = ("COMPLETE", "INCOMPLETE", "CONTRADICTED")
REQUIREMENT_STATES = ("SATISFIED", "UNRESOLVED", "CONTRADICTED")

TEMPORAL_WINDOW_UNRESOLVED = "TEMPORAL_WINDOW_UNRESOLVED"
UNSPECIFIED_CONTRACT_CASE = "UNSPECIFIED_CONTRACT_CASE"
MISSING_REQUIRED_DATUM = "MISSING_REQUIRED_DATUM"


@dataclass(frozen=True)
class E1EvaluationResult:
    """Pure evaluator output ready for explicit persistence by a caller."""

    evaluation: EpistemicEvaluation
    relations: tuple[EvidenceRelation, ...]


def _deterministic_relation_id(target_id: str, requirement_id: str, evidence_id: str) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"prama-dynamagh:e1-c2:{target_id}:{requirement_id}:{evidence_id}",
        )
    )


def _relation_body(
    *,
    relation_state: str,
    relation_basis: Mapping[str, Any],
    observer_version: str,
    contract_version: str,
) -> dict[str, Any]:
    return {
        "canonicalization_version": E1_CANONICALIZATION_VERSION,
        "contract_version": contract_version,
        "observer_version": observer_version,
        "relation_basis": dict(relation_basis),
        "relation_state": relation_state,
    }


def build_evidence_relation(
    *,
    target_id: str,
    requirement_id: str,
    evidence_id: str,
    relation_state: str,
    relation_basis: Mapping[str, Any],
    observer_version: str = E1_C2_OBSERVER_VERSION,
    contract_version: str = E1_C2_CONTRACT_VERSION,
    relation_id: str | None = None,
    created_at: datetime | None = None,
) -> EvidenceRelation:
    if relation_state not in RELATION_STATES:
        raise ValueError("unsupported E1-C2 relation state")
    if not relation_basis:
        raise ValueError("relation_basis is required")
    values: dict[str, Any] = {
        "target_id": target_id,
        "requirement_id": requirement_id,
        "evidence_id": evidence_id,
        "relation_state": relation_state,
        "relation_basis": dict(relation_basis),
        "observer_version": observer_version,
        "contract_version": contract_version,
        "canonical_hash": canonical_hash(
            _relation_body(
                relation_state=relation_state,
                relation_basis=relation_basis,
                observer_version=observer_version,
                contract_version=contract_version,
            )
        ),
    }
    if relation_id is not None:
        values["relation_id"] = relation_id
    if created_at is not None:
        values["created_at"] = created_at
    return EvidenceRelation(**values)


def _relation_record(relation: EvidenceRelation) -> dict[str, Any]:
    return {
        "relation_id": relation.relation_id,
        "target_id": relation.target_id,
        "requirement_id": relation.requirement_id,
        "evidence_id": relation.evidence_id,
        "relation_state": relation.relation_state,
        "relation_basis": relation.relation_basis,
        "observer_version": relation.observer_version,
        "contract_version": relation.contract_version,
        "canonical_hash": relation.canonical_hash,
    }


def build_e1_evidence_set_hash(
    evidence: Iterable[Evidence],
    typed_evidence_by_id: Mapping[str, CryptoPriceEvidence],
    *,
    admission_version: str = E1_ADMISSION_VERSION,
) -> str:
    """Hash only the existing upstream-eligible Evidence set.

    ``LIMITED`` remains eligible because the existing gate routes it through
    the workflow as reviewable evidence; ``REJECTED`` is never consumed.
    """

    items = []
    for item in sorted(
        (item for item in evidence if item.admissibility in E1_ELIGIBLE_ADMISSION_STATES),
        key=lambda item: item.evidence_id,
    ):
        typed = typed_evidence_by_id.get(item.evidence_id)
        items.append(
            {
                "admission_state": item.admissibility,
                "admission_version": admission_version,
                "evidence_id": item.evidence_id,
                "typed_evidence_hash": typed.canonical_hash if typed is not None else None,
            }
        )
    return canonical_hash(
        {
            "canonicalization_version": E1_CANONICALIZATION_VERSION,
            "evidence_set_hash_version": E1_EVIDENCE_SET_HASH_VERSION,
            "items": items,
        }
    )


def _unresolved_basis(
    requirement: EvidenceRequirement,
    *,
    rule: str,
    limitation: str,
    detail: Mapping[str, Any] | None = None,
) -> tuple[str, dict[str, Any], tuple[str, ...]]:
    basis: dict[str, Any] = {
        "rule": rule,
        "requirement_type": requirement.requirement_type,
        "limitation_code": limitation,
    }
    if detail:
        basis.update(detail)
    return "UNRESOLVED", basis, (limitation,)


def _target_value(target: EpistemicTarget, key: str) -> str | None:
    value = target.parameters.get(key)
    return value if isinstance(value, str) and value else None


def _typed_unavailable(requirement: EvidenceRequirement) -> tuple[str, dict[str, Any], tuple[str, ...]]:
    return _unresolved_basis(
        requirement,
        rule="typed_evidence_unavailable",
        limitation=UNSPECIFIED_CONTRACT_CASE,
    )


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _explicit_window(requirement: EvidenceRequirement) -> int | None:
    value = requirement.parameters.get("max_age_seconds")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _evaluate_value_feed_relation(
    *,
    target: EpistemicTarget,
    requirement: EvidenceRequirement,
    typed: CryptoPriceEvidence | None,
    identity_fields: tuple[str, ...],
    value_field: str,
) -> tuple[str, dict[str, Any], tuple[str, ...]]:
    """Single parameterized implementation for identity+value+temporal feeds."""

    if typed is None:
        return _typed_unavailable(requirement)
    if typed.schema_version != CRYPTO_PRICE_EVIDENCE_SCHEMA_VERSION:
        return _unresolved_basis(
            requirement,
            rule="unsupported_typed_evidence_schema",
            limitation=UNSPECIFIED_CONTRACT_CASE,
            detail={"schema_version": typed.schema_version},
        )

    requirement_type = requirement.requirement_type

    for field in identity_fields:
        if requirement_type == f"{field}_identity" or (
            # f"{field}_identity" is the canonical registry form; plain field
            # name keeps the pre-registry CRYPTO_PRICE requirements valid.
            field == {"asset": "asset", "quote_currency": "quote_currency"}.get(field)
            and requirement_type == field
        ):
            expected = _target_value(target, field)
            observed = getattr(typed, field, None)
            observed = observed if isinstance(observed, str) and observed else None
            if expected is None or observed is None:
                return _unresolved_basis(
                    requirement,
                    rule="missing_required_datum",
                    limitation=MISSING_REQUIRED_DATUM,
                    detail={"field": field},
                )
            state = "SATISFIES" if observed == expected else "CONTRADICTS"
            return state, {
                "rule": "exact_field_match" if state == "SATISFIES" else "exact_field_mismatch",
                "evidence_field": field,
                "expected_value": expected,
                "observed_value": observed,
            }, ()

    if requirement_type == f"{value_field}_value" or (
        # f"{value_field}_value" is the canonical registry form; plain field
        # name keeps the pre-registry CRYPTO_PRICE requirements valid.
        requirement_type == value_field
    ):
        try:
            observed = canonical_decimal(getattr(typed, value_field))
        except (InvalidOperation, TypeError, ValueError):
            return _unresolved_basis(
                requirement,
                rule="missing_or_invalid_typed_datum",
                limitation=MISSING_REQUIRED_DATUM,
                detail={"field": value_field},
            )
        return "SATISFIES", {
            "rule": "typed_field_present",
            "evidence_field": value_field,
            "observed_value": observed,
        }, ()

    if requirement_type == "temporal_applicability":
        max_age = _explicit_window(requirement)
        if max_age is None:
            return _unresolved_basis(
                requirement,
                rule="explicit_temporal_window_required",
                limitation=TEMPORAL_WINDOW_UNRESOLVED,
            )
        target_as_of = _parse_timestamp(target.temporal_scope.get("as_of"))
        observed_at = _parse_timestamp(typed.observed_at)
        if target_as_of is None or observed_at is None:
            return _unresolved_basis(
                requirement,
                rule="temporal_timestamp_unavailable",
                limitation=TEMPORAL_WINDOW_UNRESOLVED,
            )
        delta = abs(target_as_of - observed_at)
        delta_seconds = Decimal(delta.days * 86400 * 1_000_000 + delta.seconds * 1_000_000 + delta.microseconds) / Decimal(1_000_000)
        if delta_seconds > Decimal(max_age):
            return "NOT_APPLICABLE", {
                "rule": "explicit_temporal_window_outside",
                "target_as_of": canonical_timestamp(target_as_of),
                "observed_at": canonical_timestamp(observed_at),
                "max_age_seconds": max_age,
                "absolute_delta_seconds": canonical_decimal(delta_seconds),
            }, ()
        state = "SATISFIES"
        return state, {
            "rule": "explicit_temporal_window",
            "target_as_of": canonical_timestamp(target_as_of),
            "observed_at": canonical_timestamp(observed_at),
            "max_age_seconds": max_age,
            "absolute_delta_seconds": canonical_decimal(delta_seconds),
        }, ()

    return _unresolved_basis(
        requirement,
        rule="unsupported_requirement_type",
        limitation=UNSPECIFIED_CONTRACT_CASE,
    )


def _evaluate_claim_verification_relation(
    *,
    target: EpistemicTarget,
    requirement: EvidenceRequirement,
    typed: CryptoPriceEvidence | None,
    fields_to_compare: tuple[str, ...],
) -> tuple[str, dict[str, Any], tuple[str, ...]]:
    """Compare multiple expected fields from the Target against observed values.

    Each requirement_type maps to one comparison field; any field configured
    in the registry must appear in parameters for the comparison to apply.
    """
    if typed is None:
        return _typed_unavailable(requirement)
    if typed.schema_version != CRYPTO_PRICE_EVIDENCE_SCHEMA_VERSION:
        return _unresolved_basis(
            requirement,
            rule="unsupported_typed_evidence_schema",
            limitation=UNSPECIFIED_CONTRACT_CASE,
            detail={"schema_version": typed.schema_version},
        )

    requirement_type = requirement.requirement_type

    if requirement_type == "temporal_applicability":
        max_age = _explicit_window(requirement)
        if max_age is None:
            return _unresolved_basis(
                requirement,
                rule="explicit_temporal_window_required",
                limitation=TEMPORAL_WINDOW_UNRESOLVED,
            )
        target_as_of = _parse_timestamp(target.temporal_scope.get("as_of"))
        observed_at = _parse_timestamp(typed.observed_at)
        if target_as_of is None or observed_at is None:
            return _unresolved_basis(
                requirement,
                rule="temporal_timestamp_unavailable",
                limitation=TEMPORAL_WINDOW_UNRESOLVED,
            )
        delta = abs(target_as_of - observed_at)
        delta_seconds = Decimal(delta.days * 86400 * 1_000_000 + delta.seconds * 1_000_000 + delta.microseconds) / Decimal(1_000_000)
        if delta_seconds > Decimal(max_age):
            return "NOT_APPLICABLE", {
                "rule": "explicit_temporal_window_outside",
                "target_as_of": canonical_timestamp(target_as_of),
                "observed_at": canonical_timestamp(observed_at),
                "max_age_seconds": max_age,
                "absolute_delta_seconds": canonical_decimal(delta_seconds),
            }, ()
        return "SATISFIES", {
            "rule": "explicit_temporal_window",
            "target_as_of": canonical_timestamp(target_as_of),
            "observed_at": canonical_timestamp(observed_at),
            "max_age_seconds": max_age,
            "absolute_delta_seconds": canonical_decimal(delta_seconds),
        }, ()

    if requirement_type not in fields_to_compare:
        return _unresolved_basis(
            requirement,
            rule="unsupported_requirement_type_for_engine",
            limitation=UNSPECIFIED_CONTRACT_CASE,
            detail={"requirement_type": requirement_type, "engine": "claim_verification"},
        )

    expected = target.parameters.get(requirement_type)
    observed = getattr(typed, requirement_type, None)
    if expected is None or observed is None:
        return _unresolved_basis(
            requirement,
            rule="missing_required_datum",
            limitation=MISSING_REQUIRED_DATUM,
            detail={"field": requirement_type, "has_expected": expected is not None, "has_observed": observed is not None},
        )

    params = requirement.parameters or {}
    if "max_abs_delta" in params and requirement_type in params.get("numeric_fields", ()):
        try:
            delta = abs(Decimal(str(expected)) - Decimal(str(observed)))
            if delta > Decimal(str(params["max_abs_delta"])):
                return "CONTRADICTS", {
                    "rule": "numeric_tolerance_exceeded",
                    "field": requirement_type,
                    "expected_value": str(expected),
                    "observed_value": str(observed),
                    "absolute_delta": str(delta),
                    "tolerance": str(params["max_abs_delta"]),
                }, ()
        except (InvalidOperation, TypeError, ValueError):
            return _unresolved_basis(
                requirement,
                rule="numeric_comparison_failed",
                limitation=UNSPECIFIED_CONTRACT_CASE,
                detail={"field": requirement_type},
            )
        return "SATISFIES", {
            "rule": "numeric_tolerance_match",
            "field": requirement_type,
            "expected_value": str(expected),
            "observed_value": str(observed),
            "absolute_delta": str(abs(Decimal(str(expected)) - Decimal(str(observed)))),
            "tolerance": str(params["max_abs_delta"]),
        }, ()

    state = "SATISFIES" if observed == expected else "CONTRADICTS"
    return state, {
        "rule": "exact_field_match" if state == "SATISFIES" else "exact_field_mismatch",
        "field": requirement_type,
        "expected_value": str(expected),
        "observed_value": str(observed),
    }, ()


def _evaluate_requirement_relation(
    *,
    target: EpistemicTarget,
    requirement: EvidenceRequirement,
    typed: CryptoPriceEvidence | None,
) -> tuple[str, dict[str, Any], tuple[str, ...]]:
    config = registry_lookup(target.target_type)
    if config is None:
        return _unresolved_basis(
            requirement,
            rule="unsupported_target_type",
            limitation=UNSPECIFIED_CONTRACT_CASE,
            detail={"target_type": target.target_type},
        )

    engine = config.get("engine")
    if engine == "value_feed":
        return _evaluate_value_feed_relation(
            target=target,
            requirement=requirement,
            typed=typed,
            identity_fields=tuple(config["identity_fields"]),
            value_field=config["value_field"],
        )
    if engine == "claim_verification":
        return _evaluate_claim_verification_relation(
            target=target,
            requirement=requirement,
            typed=typed,
            fields_to_compare=config.get("fields_to_compare", ()),
        )

    return _unresolved_basis(
        requirement,
        rule="unsupported_engine",
        limitation=UNSPECIFIED_CONTRACT_CASE,
        detail={"engine": engine},
    )


def _requirement_state(
    requirement: EvidenceRequirement,
    relations: Iterable[EvidenceRelation],
) -> dict[str, Any]:
    related = sorted(relations, key=lambda relation: (relation.evidence_id, relation.relation_id))
    supporting = [relation.relation_id for relation in related if relation.relation_state == "SATISFIES"]
    contradicting = [relation.relation_id for relation in related if relation.relation_state == "CONTRADICTS"]
    unresolved = [relation.relation_id for relation in related if relation.relation_state == "UNRESOLVED"]
    not_applicable = [relation.relation_id for relation in related if relation.relation_state == "NOT_APPLICABLE"]
    if contradicting:
        state = "CONTRADICTED"
    elif supporting:
        state = "SATISFIED"
    else:
        state = "UNRESOLVED"
    return {
        "requirement_id": requirement.requirement_id,
        "requirement_type": requirement.requirement_type,
        "required": requirement.required,
        "state": state,
        "supporting_relation_ids": supporting,
        "contradicting_relation_ids": contradicting,
        "unresolved_relation_ids": unresolved,
        "not_applicable_relation_ids": not_applicable,
    }


def _evaluation_body(
    *,
    target: EpistemicTarget,
    requirements: list[EvidenceRequirement],
    evidence_set_hash: str,
    requirement_states: list[dict[str, Any]],
    relations: list[EvidenceRelation],
    contradictions: list[dict[str, Any]],
    limitations: list[str],
    structural_state: str,
    observer_version: str,
    contract_version: str,
    algorithm_version: str,
    source_evidence_ids: list[str],
) -> dict[str, Any]:
    return {
        "algorithm_version": algorithm_version,
        "canonicalization_version": E1_CANONICALIZATION_VERSION,
        "contract_version": contract_version,
        "contradictions": contradictions,
        "evidence_set_hash": evidence_set_hash,
        "limitations": limitations,
        "observer_version": observer_version,
        "relations": [
            {
                "evidence_id": relation.evidence_id,
                "requirement_id": relation.requirement_id,
                "relation_basis": relation.relation_basis,
                "relation_state": relation.relation_state,
                "canonical_hash": relation.canonical_hash,
            }
            for relation in sorted(relations, key=lambda item: (item.requirement_id, item.evidence_id))
        ],
        "requirement_states": requirement_states,
        "source_evidence_ids": source_evidence_ids,
        "structural_state": structural_state,
        "target": {
            "canonical_hash": target.canonical_hash,
            "parameters": target.parameters,
            "target_type": target.target_type,
            "temporal_scope": target.temporal_scope,
        },
        "requirements": [
            {
                "canonical_hash": requirement.canonical_hash,
                "parameters": requirement.parameters,
                "required": requirement.required,
                "requirement_type": requirement.requirement_type,
            }
            for requirement in sorted(requirements, key=lambda item: item.requirement_id)
        ],
    }


def evaluate_crypto_price(
    *,
    target: EpistemicTarget,
    requirements: Iterable[EvidenceRequirement],
    evidence: Iterable[Evidence],
    typed_evidence_by_id: Mapping[str, CryptoPriceEvidence],
    mandate_id: str | None = None,
    observer_version: str = E1_C2_OBSERVER_VERSION,
    contract_version: str = E1_C2_CONTRACT_VERSION,
    algorithm_version: str = E1_C2_ALGORITHM_VERSION,
) -> E1EvaluationResult:
    """Evaluate one E1 target using only structured, eligible persisted data."""

    ordered_requirements = sorted(list(requirements), key=lambda item: item.requirement_id)
    eligible_evidence = sorted(
        [item for item in evidence if item.admissibility in E1_ELIGIBLE_ADMISSION_STATES],
        key=lambda item: item.evidence_id,
    )
    evidence_set_hash = build_e1_evidence_set_hash(eligible_evidence, typed_evidence_by_id)

    relation_rows: list[EvidenceRelation] = []
    limitations: set[str] = set()
    relation_by_requirement: dict[str, list[EvidenceRelation]] = {item.requirement_id: [] for item in ordered_requirements}

    for evidence_item in eligible_evidence:
        typed = typed_evidence_by_id.get(evidence_item.evidence_id)
        for requirement in ordered_requirements:
            if evidence_item.source_intent is not None and evidence_item.source_intent != target.target_type:
                relation_state, relation_basis, relation_limitations = (
                    "NOT_APPLICABLE",
                    {
                        "rule": "intent_not_applicable",
                        "expected_intent": target.target_type,
                        "observed_intent": evidence_item.source_intent,
                    },
                    (),
                )
            else:
                relation_state, relation_basis, relation_limitations = _evaluate_requirement_relation(
                    target=target,
                    requirement=requirement,
                    typed=typed,
                )
            limitations.update(relation_limitations)
            relation = build_evidence_relation(
                target_id=target.target_id,
                requirement_id=requirement.requirement_id,
                evidence_id=evidence_item.evidence_id,
                relation_state=relation_state,
                relation_basis=relation_basis,
                observer_version=observer_version,
                contract_version=contract_version,
                relation_id=_deterministic_relation_id(
                    target.target_id,
                    requirement.requirement_id,
                    evidence_item.evidence_id,
                ),
            )
            relation_rows.append(relation)
            relation_by_requirement[requirement.requirement_id].append(relation)

    requirement_states = [
        _requirement_state(requirement, relation_by_requirement[requirement.requirement_id])
        for requirement in ordered_requirements
    ]
    contradictions = [
        {
            "requirement_id": state["requirement_id"],
            "supporting_relation_ids": state["supporting_relation_ids"],
            "contradicting_relation_ids": state["contradicting_relation_ids"],
        }
        for state in requirement_states
        if state["contradicting_relation_ids"]
    ]
    required_states = [state["state"] for state in requirement_states if state["required"]]
    structural_state = (
        "CONTRADICTED"
        if "CONTRADICTED" in required_states
        else "INCOMPLETE"
        if "UNRESOLVED" in required_states
        else "COMPLETE"
    )
    source_evidence_ids = [item.evidence_id for item in eligible_evidence]
    evaluation_values: dict[str, Any] = {
        "mandate_id": mandate_id or target.mandate_id,
        "target_id": target.target_id,
        "evidence_set_hash": evidence_set_hash,
        "requirement_states": requirement_states,
        "relations": [_relation_record(relation) for relation in relation_rows],
        "contradictions": contradictions,
        "limitations": sorted(limitations),
        "structural_state": structural_state,
        "observer_version": observer_version,
        "contract_version": contract_version,
        "algorithm_version": algorithm_version,
        "source_evidence_ids": source_evidence_ids,
    }
    evaluation_values["canonical_hash"] = canonical_hash(
        _evaluation_body(
            target=target,
            requirements=ordered_requirements,
            evidence_set_hash=evidence_set_hash,
            requirement_states=requirement_states,
            relations=relation_rows,
            contradictions=contradictions,
            limitations=sorted(limitations),
            structural_state=structural_state,
            observer_version=observer_version,
            contract_version=contract_version,
            algorithm_version=algorithm_version,
            source_evidence_ids=source_evidence_ids,
        )
    )
    return E1EvaluationResult(
        evaluation=EpistemicEvaluation(**evaluation_values),
        relations=tuple(relation_rows),
    )


def replay_crypto_price(**kwargs: Any) -> E1EvaluationResult:
    """Replay is the same pure function over the same persisted artifacts."""

    return evaluate_crypto_price(**kwargs)


def persist_e1_evaluation(session: Any, result: E1EvaluationResult) -> EpistemicEvaluation:
    """Persist the already-computed immutable relations and evaluation."""

    session.add_all(list(result.relations))
    session.add(result.evaluation)
    session.flush()
    return result.evaluation
