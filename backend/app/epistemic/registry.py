"""Declarative registry for epistemic target types.

New intents are added here, never as new modules. Each entry names an engine
plus a small piece of configuration. Versioned so that replays can pin the
exact registry used at evaluation time.
"""

REGISTRY_SCHEMA_VERSION = "epistemic-registry-v0.1"

# Engine identifiers; no engine code lives in this file.
ENGINE_VALUE_FEED = "value_feed"
ENGINE_CLAIM_VERIFICATION = "claim_verification"


VALUE_FEED_CRYPTO_PRICE_V01 = {
    "engine": ENGINE_VALUE_FEED,
    "engine_version": "value-feed-v0.1",
    "identity_fields": ["asset", "quote_currency"],
    "value_field": "price_value",
    "temporal_window_field": "as_of",
}


CLAIM_VERIFICATION_DEFAULTS_V01 = {
    "engine": ENGINE_CLAIM_VERIFICATION,
    "engine_version": "claim-verification-v0.1",
    "comparison_rules": {
        "exact_match": ["asset", "quote_currency"],
        "numeric_tolerance": [],
        "hash_match": [],
        "boolean_match": [],
    },
}


REGISTRY: dict[str, dict] = {
    "CRYPTO_PRICE": VALUE_FEED_CRYPTO_PRICE_V01,
}


def lookup(target_type: str) -> dict | None:
    """Return the registered config for ``target_type`` or None.

    The caller decides how to fail; the registry itself keeps no policy.
    """

    return REGISTRY.get(target_type)
