"""Deterministic E1-C1 domain and persistence constructors.

This module defines only the foundational typed contracts.  It does not
evaluate relations, invoke PRAMA, or connect the contracts to Decision Gate.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
from typing import Any, Mapping

from eth_hash.auto import keccak

from app.domain.mandates import CryptoPriceEvidence, EpistemicTarget, EvidenceRequirement


E1_CANONICALIZATION_VERSION = "e1-canonical-v0.1"
E1_TARGET_CONTRACT_VERSION = "crypto-price-target-v0.1"
E1_REQUIREMENT_CONTRACT_VERSION = "crypto-price-requirement-v0.1"
CRYPTO_PRICE_EVIDENCE_SCHEMA_VERSION = "crypto-price-evidence-v0.1"
CRYPTO_PRICE_REQUIREMENT_TYPES = (
    "asset_identity",
    "quote_currency",
    "price_value",
    "temporal_applicability",
)


def canonical_timestamp(value: datetime) -> str:
    """Return an explicit UTC timestamp representation for canonical bodies."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("canonical timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonical_decimal(value: Decimal | int | str) -> str:
    """Return a float-free, deterministic decimal representation."""

    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError("canonical decimals do not accept bool or float values")
    try:
        decimal = value if isinstance(value, Decimal) else Decimal(value)
    except Exception as error:
        raise ValueError("invalid decimal value") from error
    if not decimal.is_finite():
        raise ValueError("canonical decimals must be finite")
    if decimal == 0:
        return "0"
    return format(decimal.normalize(), "f")


def _canonical_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, Decimal):
        return canonical_decimal(value)
    if isinstance(value, float):
        raise TypeError("canonical bodies do not accept float values")
    if isinstance(value, datetime):
        return canonical_timestamp(value)
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("canonical object keys must be strings")
        return {key: _canonical_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    raise TypeError(f"unsupported canonical value type: {type(value).__name__}")


def canonical_json(value: Any) -> bytes:
    """Serialize the explicit E1 canonical body contract."""

    return json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return "0x" + keccak(canonical_json(value)).hex()


def _require_nonempty_string(name: str, value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _crypto_price_parameters(asset: str, quote_currency: str, as_of: datetime | None) -> tuple[dict[str, Any], dict[str, Any]]:
    _require_nonempty_string("asset", asset)
    _require_nonempty_string("quote_currency", quote_currency)
    canonical_as_of = None if as_of is None else canonical_timestamp(as_of)
    parameters = {
        "asset": asset,
        "quote_currency": quote_currency,
        "as_of": canonical_as_of,
    }
    temporal_scope = {"as_of": canonical_as_of}
    return parameters, temporal_scope


def _target_body(*, target_type: str, parameters: Mapping[str, Any], temporal_scope: Mapping[str, Any], contract_version: str) -> dict[str, Any]:
    return {
        "canonicalization_version": E1_CANONICALIZATION_VERSION,
        "contract_version": contract_version,
        "parameters": dict(parameters),
        "target_type": target_type,
        "temporal_scope": dict(temporal_scope),
    }


def build_crypto_price_target(
    *,
    mandate_id: str,
    asset: str,
    quote_currency: str,
    as_of: datetime | None,
    target_id: str | None = None,
    contract_version: str = E1_TARGET_CONTRACT_VERSION,
    created_at: datetime | None = None,
) -> EpistemicTarget:
    """Construct a typed target without parsing Mandate text."""

    parameters, temporal_scope = _crypto_price_parameters(asset, quote_currency, as_of)
    body = _target_body(
        target_type="CRYPTO_PRICE",
        parameters=parameters,
        temporal_scope=temporal_scope,
        contract_version=contract_version,
    )
    values: dict[str, Any] = {
        "mandate_id": mandate_id,
        "target_type": "CRYPTO_PRICE",
        "parameters": parameters,
        "temporal_scope": temporal_scope,
        "contract_version": contract_version,
        "canonical_hash": canonical_hash(body),
    }
    if target_id is not None:
        values["target_id"] = target_id
    if created_at is not None:
        values["created_at"] = created_at
    return EpistemicTarget(**values)


def _requirement_body(*, requirement_type: str, parameters: Mapping[str, Any], required: bool, contract_version: str) -> dict[str, Any]:
    return {
        "canonicalization_version": E1_CANONICALIZATION_VERSION,
        "contract_version": contract_version,
        "parameters": dict(parameters),
        "required": required,
        "requirement_type": requirement_type,
    }


def build_evidence_requirement(
    *,
    target_id: str,
    requirement_type: str,
    parameters: Mapping[str, Any] | None = None,
    required: bool = True,
    requirement_id: str | None = None,
    contract_version: str = E1_REQUIREMENT_CONTRACT_VERSION,
    created_at: datetime | None = None,
) -> EvidenceRequirement:
    """Build a requirement, validated against the epistemic registry.

    CRYPTO_PRICE requirements keep their pre-registry validity; any other
    requirement_type must resolve to a registered engine configuration.
    """
    from app.epistemic.registry import lookup as registry_lookup

    if requirement_type not in CRYPTO_PRICE_REQUIREMENT_TYPES:
        target_type = parameters and parameters.get("target_type") if isinstance(parameters, Mapping) else None
        if target_type is None or registry_lookup(target_type) is None:
            raise ValueError(
                "unsupported requirement_type: not a registered epistemic engine type "
                f"({requirement_type!r})"
            )
    normalized_parameters = dict(parameters or {})
    body = _requirement_body(
        requirement_type=requirement_type,
        parameters=normalized_parameters,
        required=required,
        contract_version=contract_version,
    )
    values: dict[str, Any] = {
        "target_id": target_id,
        "requirement_type": requirement_type,
        "parameters": normalized_parameters,
        "required": required,
        "contract_version": contract_version,
        "canonical_hash": canonical_hash(body),
    }
    if requirement_id is not None:
        values["requirement_id"] = requirement_id
    if created_at is not None:
        values["created_at"] = created_at
    return EvidenceRequirement(**values)


def build_crypto_price_evidence(
    *,
    evidence_id: str,
    asset: str,
    quote_currency: str,
    price_value: Decimal | int | str,
    observed_at: datetime,
    crypto_price_evidence_id: str | None = None,
    schema_version: str = CRYPTO_PRICE_EVIDENCE_SCHEMA_VERSION,
    created_at: datetime | None = None,
) -> CryptoPriceEvidence:
    """Construct typed evidence; no provider payload is interpreted here."""

    _require_nonempty_string("asset", asset)
    _require_nonempty_string("quote_currency", quote_currency)
    canonical_price = canonical_decimal(price_value)
    canonical_observed_at = canonical_timestamp(observed_at)
    body = {
        "asset": asset,
        "canonicalization_version": E1_CANONICALIZATION_VERSION,
        "observed_at": canonical_observed_at,
        "price_value": canonical_price,
        "quote_currency": quote_currency,
        "schema_version": schema_version,
    }
    values: dict[str, Any] = {
        "evidence_id": evidence_id,
        "asset": asset,
        "quote_currency": quote_currency,
        "price_value": Decimal(canonical_price),
        "observed_at": observed_at.astimezone(timezone.utc),
        "schema_version": schema_version,
        "canonical_hash": canonical_hash(body),
    }
    if crypto_price_evidence_id is not None:
        values["crypto_price_evidence_id"] = crypto_price_evidence_id
    if created_at is not None:
        values["created_at"] = created_at
    return CryptoPriceEvidence(**values)


TARGET_BUILDER_VERSION = "acquisition-target-builder-v0.1"


def build_target_from_acquisition(
    acquisition: Any,
    *,
    mandate_id: str,
    target_id: str | None = None,
    created_at: datetime | None = None,
) -> EpistemicTarget | None:
    """Derive an EpistemicTarget exclusively from AcquisitionTask identity fields.

    Returns None when the task has no schema version set (legacy rows; nothing
    to build). Identity comes only from target_* columns written at enqueue
    time; Evidence is never consulted here.
    """
    if not acquisition.target_schema_version:
        return None
    parameters = {
        "subject": acquisition.target_subject,
        "property": acquisition.target_property,
        "unit": acquisition.target_unit,
        "constraints": dict(acquisition.target_constraints or {}),
        "schema_version": acquisition.target_schema_version,
        # Pre-registry v0.1 compatibility: the evaluator reads asset/quote_currency.
        "asset": acquisition.target_subject,
        "quote_currency": acquisition.target_unit,
    }
    temporal_scope = dict(acquisition.temporal_scope or {})
    body = _target_body(
        target_type=acquisition.requested_intent or "UNKNOWN",
        parameters=parameters,
        temporal_scope=temporal_scope,
        contract_version=TARGET_BUILDER_VERSION,
    )
    values: dict[str, Any] = {
        "mandate_id": mandate_id,
        "target_type": acquisition.requested_intent or "UNKNOWN",
        "parameters": parameters,
        "temporal_scope": temporal_scope,
        "contract_version": TARGET_BUILDER_VERSION,
        "canonical_hash": canonical_hash(body),
    }
    if target_id is not None:
        values["target_id"] = target_id
    if created_at is not None:
        values["created_at"] = created_at
    return EpistemicTarget(**values)
