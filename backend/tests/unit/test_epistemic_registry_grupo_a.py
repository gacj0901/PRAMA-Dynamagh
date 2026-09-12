"""Grupo A (value feed) registry structural invariants."""

from app.epistemic.registry import REGISTRY, REGISTRY_SCHEMA_VERSION, lookup, ENGINE_VALUE_FEED

GROUP_A = [
    "CRYPTO_PRICE", "STOCK_PRICE", "CURRENCY_EXCHANGE", "FX_NOW",
    "GAS_PRICE", "GRID_POWER_PRICE", "LIVE_SHELF_PRICE",
    "MACRO_ECONOMIC_INDICATOR", "MINING_HASHPRICE_VERIFY", "FINANCIAL_DATA",
    "TOKEN_HOLDER_COUNT", "TVL_LOOKUP", "WALLET_BALANCE_CHECK",
    "SKU_IN_STOCK", "WAREHOUSE_INVENTORY", "WEATHER_FORECAST",
    "WEATHER_CHECK", "ROUTE_ETA", "SHIP_RATE_ETA", "LIQUIDITY_DEPTH_VERIFY",
    "LIVE_PORT_CONGESTION",
]


def test_all_group_a_registered():
    for name in GROUP_A:
        assert name in REGISTRY, f"{name} missing from registry"
        config = REGISTRY[name]
        assert config["engine"] == ENGINE_VALUE_FEED
        assert config["canonical_intent_id"] == name
        assert config["engine_version"] == "value-feed-v0.1"


def test_registry_determinism():
    # Each entry must load and key sets must be stable
    for name in GROUP_A:
        config = REGISTRY[name]
        assert isinstance(config["identity_fields"], list)
        assert isinstance(config["acquisition_parameters"], dict)
        assert isinstance(config["normalized_output_mapping"], dict)
        assert "value_field" in config


def test_registry_schema_versioned():
    assert REGISTRY_SCHEMA_VERSION == "epistemic-registry-v0.2"


def test_registry_query_by_intent():
    assert lookup("STOCK_PRICE") is not None
    assert lookup("UNKNOWN_INTENT_V999") is None


def test_value_feed_field_consistency():
    for name in GROUP_A:
        config = REGISTRY[name]
        # identity_fields must not be empty
        assert len(config["identity_fields"]) > 0
        # value_field must not overlap with identity fields
        assert config["value_field"] not in config["identity_fields"]


def test_all_value_feeds_have_temporal_window():
    for name in GROUP_A:
        config = REGISTRY[name]
        assert "temporal_window_field" in config
