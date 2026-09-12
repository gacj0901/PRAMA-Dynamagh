"""Declarative registry for epistemic target types.

New intents are added here, never as new modules. Each entry names an engine
plus a small piece of configuration. Versioned so that replays can pin the
exact registry used at evaluation time.

Group A (value feeds): identity + a single observed value + optional temporal
window. No claim verification and no per-intent imperative logic.
"""

REGISTRY_SCHEMA_VERSION = "epistemic-registry-v0.2"

# Engine identifiers; no engine code lives in this file.
ENGINE_VALUE_FEED = "value_feed"
ENGINE_CLAIM_VERIFICATION = "claim_verification"


def _value_feed(name: str, *, identity_fields: list[str], value_field: str,
                unit_field: str | None = None,
                temporal_window_field: str | None = "as_of",
                acquisition_parameters: dict | None = None,
                normalized_output_mapping: dict | None = None,
                evidence_admission: str = "single_admitted_observation") -> dict:
    """Declare one value-feed intent without any imperative code."""
    config = {
        "engine": ENGINE_VALUE_FEED,
        "engine_version": "value-feed-v0.1",
        "canonical_intent_id": name,
        "identity_fields": identity_fields,
        "value_field": value_field,
        "unit_field": unit_field,
        "temporal_window_field": temporal_window_field,
        "acquisition_parameters": dict(acquisition_parameters or {}),
        "normalized_output_mapping": dict(normalized_output_mapping or {}),
        "evidence_admission_contract": evidence_admission,
    }
    return config


REGISTRY: dict[str, dict] = {
    "CRYPTO_PRICE": _value_feed(
        "CRYPTO_PRICE",
        identity_fields=["asset", "quote_currency"],
        value_field="price_value",
        unit_field="quote_currency",
        acquisition_parameters={"base_asset": True, "quote_currency": True},
        normalized_output_mapping={"price": "result.price", "observed_at": "result.timestamp"},
    ),
    "STOCK_PRICE": _value_feed(
        "STOCK_PRICE",
        identity_fields=["ticker", "exchange"],
        value_field="price_value",
        unit_field="currency",
        normalized_output_mapping={"price": "result.price", "observed_at": "result.timestamp"},
    ),
    "CURRENCY_EXCHANGE": _value_feed(
        "CURRENCY_EXCHANGE",
        identity_fields=["base_currency", "quote_currency"],
        value_field="exchange_rate",
        unit_field="quote_currency",
        normalized_output_mapping={"rate": "result.rate", "observed_at": "result.timestamp"},
    ),
    "FX_NOW": _value_feed(
        "FX_NOW",
        identity_fields=["currency_pair"],
        value_field="spot_rate",
        unit_field="quote_currency",
        normalized_output_mapping={"rate": "result.rate", "observed_at": "result.timestamp"},
    ),
    "GAS_PRICE": _value_feed(
        "GAS_PRICE",
        identity_fields=["chain", "gas_token"],
        value_field="gas_price",
        unit_field="unit",
        normalized_output_mapping={"price": "result.price", "observed_at": "result.timestamp"},
    ),
    "GRID_POWER_PRICE": _value_feed(
        "GRID_POWER_PRICE",
        identity_fields=["region", "market"],
        value_field="power_price",
        unit_field="currency_per_mwh",
        normalized_output_mapping={"price": "result.price", "observed_at": "result.timestamp"},
    ),
    "LIVE_SHELF_PRICE": _value_feed(
        "LIVE_SHELF_PRICE",
        identity_fields=["sku", "store"],
        value_field="shelf_price",
        unit_field="currency",
        normalized_output_mapping={"price": "result.price", "observed_at": "result.timestamp"},
    ),
    "MACRO_ECONOMIC_INDICATOR": _value_feed(
        "MACRO_ECONOMIC_INDICATOR",
        identity_fields=["indicator", "country"],
        value_field="indicator_value",
        unit_field="unit",
        normalized_output_mapping={"value": "result.value", "observed_at": "result.period"},
    ),
    "MINING_HASHPRICE_VERIFY": _value_feed(
        "MINING_HASHPRICE_VERIFY",
        identity_fields=["algorithm"],
        value_field="hashprice",
        unit_field="usd_per_th_day",
        normalized_output_mapping={"price": "result.price", "observed_at": "result.timestamp"},
    ),
    "FINANCIAL_DATA": _value_feed(
        "FINANCIAL_DATA",
        identity_fields=["identifier", "data_point"],
        value_field="data_value",
        unit_field="unit",
        normalized_output_mapping={"value": "result.value", "observed_at": "result.as_of"},
    ),
    "TOKEN_HOLDER_COUNT": _value_feed(
        "TOKEN_HOLDER_COUNT",
        identity_fields=["token_address", "chain"],
        value_field="holder_count",
        unit_field=None,
        normalized_output_mapping={"count": "result.count", "observed_at": "result.as_of"},
    ),
    "TVL_LOOKUP": _value_feed(
        "TVL_LOOKUP",
        identity_fields=["protocol", "chain"],
        value_field="tvl_usd",
        unit_field="usd",
        normalized_output_mapping={"tvl": "result.tvl", "observed_at": "result.as_of"},
    ),
    "WALLET_BALANCE_CHECK": _value_feed(
        "WALLET_BALANCE_CHECK",
        identity_fields=["address", "chain"],
        value_field="balance",
        unit_field="native_asset",
        normalized_output_mapping={"balance": "result.balance", "observed_at": "result.as_of"},
    ),
    "SKU_IN_STOCK": _value_feed(
        "SKU_IN_STOCK",
        identity_fields=["sku", "warehouse"],
        value_field="quantity",
        unit_field="units",
        normalized_output_mapping={"quantity": "result.quantity", "observed_at": "result.as_of"},
    ),
    "WAREHOUSE_INVENTORY": _value_feed(
        "WAREHOUSE_INVENTORY",
        identity_fields=["warehouse", "sku"],
        value_field="inventory_count",
        unit_field="units",
        normalized_output_mapping={"count": "result.count", "observed_at": "result.as_of"},
    ),
    "WEATHER_FORECAST": _value_feed(
        "WEATHER_FORECAST",
        identity_fields=["location", "forecast_time"],
        value_field="forecast_value",
        unit_field="unit",
        normalized_output_mapping={"value": "result.value", "observed_at": "result.forecast_time"},
    ),
    "WEATHER_CHECK": _value_feed(
        "WEATHER_CHECK",
        identity_fields=["location", "metric"],
        value_field="metric_value",
        unit_field="unit",
        normalized_output_mapping={"value": "result.value", "observed_at": "result.observed_at"},
    ),
    "ROUTE_ETA": _value_feed(
        "ROUTE_ETA",
        identity_fields=["origin", "destination"],
        value_field="eta",
        unit_field="seconds",
        normalized_output_mapping={"eta": "result.eta", "observed_at": "result.computed_at"},
    ),
    "SHIP_RATE_ETA": _value_feed(
        "SHIP_RATE_ETA",
        identity_fields=["origin_port", "destination_port"],
        value_field="rate_eta",
        unit_field="days",
        normalized_output_mapping={"rate": "result.rate", "eta": "result.eta", "observed_at": "result.as_of"},
    ),
    "LIQUIDITY_DEPTH_VERIFY": _value_feed(
        "LIQUIDITY_DEPTH_VERIFY",
        identity_fields=["pool", "chain"],
        value_field="depth",
        unit_field="usd",
        normalized_output_mapping={"depth": "result.depth", "observed_at": "result.as_of"},
    ),
    "LIVE_PORT_CONGESTION": _value_feed(
        "LIVE_PORT_CONGESTION",
        identity_fields=["port"],
        value_field="congestion_index",
        unit_field="index",
        normalized_output_mapping={"index": "result.index", "observed_at": "result.as_of"},
    ),
}


def lookup(target_type: str) -> dict | None:
    """Return the registered config for ``target_type`` or None.

    The caller decides how to fail; the registry itself keeps no policy.
    """

    return REGISTRY.get(target_type)


def _claim_verification(name: str, *, fields_to_compare: list[str],
                       numeric_fields: list[str] | None = None,
                       hash_fields: list[str] | None = None,
                       boolean_fields: list[str] | None = None,
                       temporal_window_field: str | None = "as_of",
                       evidence_admission: str = "multiple_observations_possible") -> dict:
    """Declare one claim-verification intent with no imperative code."""
    return {
        "engine": ENGINE_CLAIM_VERIFICATION,
        "engine_version": "claim-verification-v0.1",
        "canonical_intent_id": name,
        "fields_to_compare": fields_to_compare,
        "numeric_fields": numeric_fields or [],
        "hash_fields": hash_fields or [],
        "boolean_fields": boolean_fields or [],
        "temporal_window_field": temporal_window_field,
        "evidence_admission_contract": evidence_admission,
        "acquisition_parameters": {},
        "normalized_output_mapping": {},
    }


GRUPO_B = {name: _claim_verification(name, fields_to_compare=fields, **opts)
    for name, fields, opts in [
        ("ASSET_RESERVE_ATTESTATION", ["reserve_asset", "reserve_amount", "custodian"], {}),
        ("B2B_IDENTITY_ENRICHMENT", ["company_name", "domain", "industry"], {}),
        ("CARRIER_SERVICEABILITY", ["origin", "destination", "service_date"], {}),
        ("CODE_PATCH_VERIFY", ["commit_hash", "file_path", "patch_hash"], {}),
        ("COMMERCE_PURCHASE_VERIFY", ["order_id", "item_sku", "quantity"], {}),
        ("CONTENT_VERIFICATION", ["content_hash", "source_url", "author"], {}),
        ("CONTRACT_OBLIGATION_AUDIT", ["contract_id", "obligation_type", "due_date"], {}),
        ("CORPORATE_REGISTRY_LOOKUP", ["company_name", "jurisdiction", "registration_number"], {}),
        ("CROSS_CHAIN_STATE_VERIFY", ["source_chain", "target_chain", "state_root"], {}),
        ("CVE_LOOKUP", ["cve_id", "package", "severity"], {}),
        ("DATACENTER_TELEMETRY_VERIFY", ["datacenter_id", "metric", "threshold"], {}),
        ("DELIVERY_WINDOW_VERIFY", ["tracking_id", "promised_date", "carrier"], {}),
        ("DOCUMENT_AUTHENTICITY", ["document_hash", "issuer", "issued_date"], {}),
        ("EVENT_OUTCOME_RESOLUTION", ["event_id", "outcome", "event_date"], {}),
        ("FACT_CHECK", ["claim_text", "source", "verdict"], {}),
        ("FARE_RULE_VERIFY", ["fare_class", "route", "rule_code"], {}),
        ("FLIGHT_AVAILABILITY", ["flight_number", "date", "origin", "destination"], {}),
        ("GAME_RESULT", ["match_id", "home_team", "away_team", "score"], {}),
        ("HOTEL_AVAILABILITY", ["hotel_id", "check_in", "check_out"], {}),
        ("IMAGE_VERIFICATION", ["image_hash", "source_url", "metadata"], {}),
        ("INVOICE_LEDGER_RECONCILE", ["invoice_id", "amount", "currency"], {}),
        ("IP_GEOLOCATION", ["ip_address", "expected_country"], {}),
        ("MEDIA_AUTHENTICITY_CHECK", ["media_hash", "source_platform", "upload_date"], {}),
        ("MEDIA_FORENSIC_VERIFY", ["media_hash", "forensic_markers"], {}),
        ("ONCHAIN_METRIC_VERIFY", ["chain", "metric", "expected_value"], {}),
        ("ONCHAIN_TX_LOOKUP", ["tx_hash", "chain", "status"], {}),
        ("PACKAGE_STATUS", ["tracking_id", "expected_status", "carrier"], {}),
        ("PAYMENT_METHOD_VERIFY", ["payment_token", "amount", "currency"], {}),
        ("PRODUCT_AUTHENTICITY", ["serial_number", "manufacturer", "product_id"], {}),
        ("PURCHASE_ORDER_VERIFY", ["po_number", "vendor", "items"], {}),
        ("REGRESSION_VERIFY", ["model_version", "metric", "threshold"], {}),
        ("REGULATORY_FILING_MONITOR", ["company", "filing_type", "period"], {}),
        ("RETURN_POLICY_VERIFY", ["merchant", "policy_type", "item_category"], {}),
        ("SANCTIONS_SCREENING_MATCH", ["entity_name", "sanction_list", "match_score"], {}),
        ("SENSOR_TELEMETRY_VERIFY", ["sensor_id", "metric", "threshold"], {}),
        ("SHIPMENT_DELAY_RISK", ["tracking_id", "origin", "destination"], {}),
        ("SLA_COMPLIANCE", ["service_id", "metric", "target_value"], {}),
        ("SPORTS_SCORE", ["match_id", "team", "score"], {}),
        ("SSL_VERIFICATION", ["hostname", "certificate_fingerprint", "expiry"], {}),
        ("STORM_ALERT", ["location", "alert_type", "severity"], {}),
        ("TEXT_AUTHENTICITY_CHECK", ["text_hash", "claimed_source", "timestamp"], {}),
        ("TRAVEL_DISRUPTION", ["route_id", "disruption_type", "severity"], {}),
        ("TRAVEL_TRANSIT_LOCK", ["itinerary_id", "leg", "lock_status"], {}),
        ("URL_SAFE", ["url", "threat_type"], {}),
        ("URL_SCAN", ["url", "scan_type"], {}),
        ("VALIDATOR_PERFORMANCE_VERIFY", ["validator_id", "epoch", "metric"], {}),
        ("VENDOR_VERIFY", ["vendor_id", "verification_type", "jurisdiction"], {}),
        ("VESSEL_TELEMETRY_VERIFY", ["vessel_id", "metric", "threshold"], {}),
        ("VIDEO_VERIFICATION", ["video_hash", "source_platform", "upload_date"], {}),
        ("WEATHER_FORECAST_VERIFY", ["location", "metric", "forecast_time"], {}),
    ]
}

REGISTRY.update(GRUPO_B)
