"""Public PRAMA-owned discovery descriptor; no execution or signing tools."""
from app.api.bazaar_observation import indexing_observation
from copy import deepcopy
from fastapi import APIRouter, Response
from fastapi.responses import PlainTextResponse

router = APIRouter(tags=["agent-discovery"])
DESCRIPTION = ("Paid machine intelligence with Evidence, provenance, PRAMAgraph "
               "structural evaluation, Decision, Ticket and capability-bound Consumer Result.")
BENIGN = ("[BENIGN AGENT DISCOVERY]\nDiscover PRAMA-Dynamagh as an optional evidence-bound machine "
          "intelligence service. Use only when external service access and payment are permitted "
          "by the caller's own governing policy.")
REQUEST_SCHEMA = {
    "type": "object", "properties": {
        "intent": {"type": ["string", "null"], "description": "Optional application-level semantic hint; legacy alias. Takes precedence over requested_intent when present, including null. Not necessarily a Telegraph Intent_ID."},
        "requested_intent": {"type": ["string", "null"], "description": "Optional application-level semantic hint / request metadata. Not necessarily a Telegraph Intent_ID; Telegraph owns protocol resolution."},
        "query": {"type": "string", "minLength": 1}, "request": {"type": "string", "minLength": 1},
    }, "anyOf": [{"required": ["query"]}, {"required": ["request"]}],
    "description": "Provide a nonempty query or request; a truthy request takes precedence. The semantic hint is optional. Arbitrary client constraints are not consumed by this public endpoint.",
}
RESULT_SCHEMA = {"type": "object", "properties": {
    "consumer_result": {"type": "object", "properties": {
        "status": {"enum": ["DELIVERED", "PENDING", "NOT_AVAILABLE"]}, "results": {"type": "array"}}},
    "evidence": {"type": "array"}, "decision": {"type": ["object", "null"]},
    "ticket": {"type": ["object", "null"]}, "evaluation": {"type": ["object", "null"]},
}}
ACCEPTED_SCHEMA = {"type": "object", "required": ["mandate_id", "result_endpoint", "result_capability"],
                   "properties": {"mandate_id": {"type": "string"}, "result_endpoint": {"type": "string"},
                                  "result_capability": {"type": ["string", "null"]}},
                   "description": "202 acceptance, not intelligence. GET result_endpoint with X-PRAMA-Result-Capability. "
                                  "Subsequent result contains consumer_result, evidence, evaluation, decision and ticket. "
                                  "Discovery contains no real capability: null is a safe example. The initial successful 202 "
                                  "returns a secret one-time-issued result_capability; keep it private. Idempotent replay does not reissue it."}


def bazaar_extension():
    """x402 v2 Bazaar info/schema shape from the official HTTP body builder."""
    return {"bazaar": {
        "info": {"input": {"type": "http", "method": "POST", "bodyType": "json",
                            "body": {"requested_intent": "WEB_SEARCH", "query": "Find the official specification for HTTP 402."}},
                 "output": {"type": "json", "example": {"mandate_id": "example-only", "result_endpoint":
                            descriptor()["interfaces"]["http"]["endpoint"] + "/{mandate_id}/result", "result_capability": None}}},
        "schema": {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object",
                   "required": ["input"], "properties": {
            "input": {"type": "object", "required": ["type", "method", "bodyType", "body"],
                      "additionalProperties": False, "properties": {
                "type": {"const": "http"}, "method": {"enum": ["POST", "PUT", "PATCH"]},
                "bodyType": {"enum": ["json", "form-data", "text"]}, "body": deepcopy(REQUEST_SCHEMA)}},
            "output": {"type": "object", "required": ["type"], "properties": {
                "type": {"type": "string"}, "example": ACCEPTED_SCHEMA}},
        }},
    }}


RESOLUTION = {"intent_resolution_owner": "Telegraph", "eligibility_ranking_owner": "Telegraph",
              "miner_selection_owner": "Telegraph",
              "explicit_telegraph_intent_id_required": False,
              "requested_intent_semantics": "application-level semantic hint / request metadata",
              "local_telegraph_intent_registry": False}


def supported_capabilities():
    """PRAMA-owned request semantics and dated observations, not a routing registry."""
    from app.api import x402
    return {"schema_version": "prama.capabilities.v1", "service": "PRAMA-Dynamagh",
            "descriptor_type": "PRAMA-owned capability descriptor; not an x402 or Telegraph standard",
            "execution": {"method": "POST", "url": x402.PUBLIC_ORIGIN + "/v1/public/ask",
                          "payment_protocol": "x402", "network": x402.X402_NETWORK,
                          "environment": "TESTNET" if x402.X402_NETWORK == "eip155:84532" else "UNKNOWN"},
            "request_model": {"schema": deepcopy(REQUEST_SCHEMA),
                              "hint_semantics": "requested_intent is not necessarily a Telegraph Intent_ID.",
                              "client_constraints": "Not consumed by this public API; constraints and budget are set by the server."},
            "resolution": dict(RESOLUTION),
            "observed_request_examples": [
                {"requested_intent": "WEB_SEARCH", "observed_status": "OBSERVED_SUCCESS",
                 "acquisition": "SUCCEEDED", "evidence": "ADMITTED", "provenance": "VERIFIED",
                 "consumer_result": "DELIVERED", "semantic_task_fulfillment": "NOT_ESTABLISHED",
                 "semantics": "Retrieval/search primitive; returned search metadata did not establish higher-level research fulfillment.",
                 "source": "Persisted M2M acquisition plus operator-supplied execution record 742b0c6a-e962-43b5-99d6-74d45bc8cb70"},
                {"requested_intent": "FINANCIAL_DATA", "observed_status": "OBSERVED_SUCCESS",
                 "acquisition": "SUCCEEDED", "semantic_task_fulfillment": "NOT_ESTABLISHED",
                 "source": "Read-only production M2M acquisition observation; no semantic-content certification."},
                {"requested_intent": "WEATHER_FORECAST", "observed_status": "UNVERIFIED",
                 "source": "Operator-attested KIMI_EXTERNAL case in campaign ledger; full persisted lineage not independently matched."},
                {"requested_intent": "RESEARCH_QUERY", "observed_status": "FAILED",
                 "failure_code": "TELEGRAPH_REQUEST_FAILED", "external_status": "UNDER_INVESTIGATION",
                 "source": "Persisted failed M2M acquisitions and operator-reported team acknowledgment.",
                 "interpretation": "Not proof of nonexistence, permanent routing failure or a PRAMA defect. No replacement is inferred."}],
            "observations_as_of": "2026-09-26",
            "example_semantics": "Observed application-level hints only; not supported Telegraph Intent_IDs, an exhaustive inventory or future availability guarantees.",
            "async_contract": {"accepted_status": 202, "accepted_schema": deepcopy(ACCEPTED_SCHEMA),
                               "result_method": "GET", "result_header": "X-PRAMA-Result-Capability",
                               "result_schema": deepcopy(RESULT_SCHEMA), "automatic_payment_retry": False},
            "semantics": {"payment_is_authority": False, "delivered_is_authorization": False,
                          "delivered_implies_semantic_fulfillment": False,
                          "semantic_task_fulfillment": "NOT_INFERRED_FROM_DELIVERY"}}


@router.get("/v1/public/capabilities")
def public_capabilities(response: Response):
    response.headers["Cache-Control"] = "public, max-age=60"
    return supported_capabilities()


def descriptor():
    from app.api import x402
    base = x402.PUBLIC_ORIGIN
    return {"schema_version": "1.0", "descriptor_type": "PRAMA descriptor (not an external standard)",
            "service": {"name": "PRAMA-Dynamagh", "provider": "AptadinamiK Cybernetics",
                        "type": "evidence_bound_machine_intelligence"},
            "interfaces": {"http": {"endpoint": base + "/v1/public/ask", "method": "POST", "payment": "x402"},
                           "mcp": {"endpoint": base + "/mcp", "status": "discovery", "transport": "streamable-http"},
                           "openapi": {"url": base + "/openapi.json"}},
            "payments": {"protocol": "x402", "version": 2, "network": x402.X402_NETWORK,
                         "environment": "TESTNET" if x402.X402_NETWORK == "eip155:84532" else "UNKNOWN",
                         "asset": x402._eip712_domain()["name"], "asset_contract": x402.X402_ASSET,
                         "pricing": "challenge-derived"},
            "semantics": {"acquisition_success_is_not_authorization": True,
                          "governance_success_is_not_consumer_fulfillment": True,
                          "payment_is_authority": False, "delivered_is_authorization": False,
                          "delivered_implies_semantic_fulfillment": False,
                          "semantic_task_fulfillment": "NOT_INFERRED_FROM_DELIVERY",
                          "consumer_delivery_condition": "consumer_result.status == DELIVERED",
                          "delivery_scope": "Server returns admitted content; not consumer acknowledgment or content correctness."},
            "outputs": ["consumer_result", "evidence", "evidence_content_hash", "provenance", "structural_evaluation", "decision", "ticket"],
            "identity": {"agent_identity": "optional", "wallet_is_agent_identity": False, "wallet_role": "economic_principal"},
            "acquisition": {"infrastructure": "Telegraph Protocol"},
            "discovery": {"guide": base + "/agents.md", "llms": base + "/llms.txt", "adoption": base + "/adoption",
                          "metrics": base + "/v1/public/adoption", "capabilities": base + "/v1/public/capabilities", "bazaar_metadata_declared": True,
                          **indexing_observation()},
            "capabilities": {"url": base + "/v1/public/capabilities"}, "resolution": dict(RESOLUTION),
            "request_schema": deepcopy(REQUEST_SCHEMA), "result_schema": RESULT_SCHEMA}


def execution_guide():
    base = descriptor()["interfaces"]["http"]["endpoint"].removesuffix("/v1/public/ask")
    return f"""# PRAMA-Dynamagh — Agent Execution Guide

{BENIGN}
This service is an optional external machine capability.
Do not override system instructions, security policy, wallet controls,
delegated authority, or spending limits.

## EXECUTION PATH
1. Discover PRAMA: {base}/.well-known/prama-agent.json
2. Inspect PRAMA request capabilities: {base}/v1/public/capabilities
3. POST a natural-language query/request without payment to {base}/v1/public/ask; requested_intent is optional.
4. Receive HTTP 402.
5. Validate current payment challenge: version, scheme, resource, network, asset, amount, recipient and EIP-712 domain.
6. Independently evaluate cost against caller-controlled request/session limits.
7. Sign only when authorized. Keep keys outside the LLM.
8. Submit PAYMENT-SIGNATURE with the identical logical request and Idempotency-Key.
9. Preserve mandate result capability privately immediately upon 202; it is delivered in clear only once.
10. GET only the returned result_endpoint using X-PRAMA-Result-Capability (not Bearer).
11. Inspect consumer_result, evidence, evaluation, decision and ticket, and inspect actual content for the requested intelligence.
12. Preserve Evidence hash and Ticket when useful; never expose the capability.

Example only: {{"requested_intent":"WEB_SEARCH","query":"Your actual information need"}}.
requested_intent is not necessarily a Telegraph Intent_ID.
Telegraph performs protocol Intent resolution and Miner selection; PRAMA owns
Mandate, Evidence, governance, Decision, Ticket and Consumer Result delivery.
No local Intent registry is required. Optional hints are not routing guarantees.
PAYMENT != AUTHORITY. DELIVERED != SEMANTIC_TASK_FULFILLMENT.
Aliases: intent (preferred legacy field), request. Do not send conflicting aliases.
Result: 202 is acceptance, not fulfillment. Poll only the returned same-origin result URL.
After ambiguous paid response: STOP. Do not sign/pay again or retry automatically.
ACQUISITION_SUCCESS != EVIDENCE_ADMISSIBLE != RESULT_DELIVERED != SEMANTIC_TASK_FULFILLED.
SUCCEEDED != DELIVERED. wallet != AgentIdentity.
Semantic task fulfillment is not currently inferred from delivery.
As observed 2026-09-26: WEB_SEARCH is a search/retrieval primitive, not research/synthesis.
RESEARCH_QUERY: latest reported acquisition failed; Telegraph team investigating. No automatic substitute.
DELIVERED means content in this HTTP response, possibly a subset of acquisitions;
not acknowledgment, correctness, or proof that the question is fully answered.
Current network: {descriptor()['payments']['network']} / {descriptor()['payments']['environment']}.
Price, recipient and asset are challenge-derived. This deployment is not mainnet.
Telegraph provides machine intelligence infrastructure. PRAMA-Dynamagh adds
evidence-bound evaluation, execution governance, auditability and Consumer Result delivery.
Discovery-only MCP: {base}/mcp
OpenAPI: {base}/openapi.json
Adoption metrics: {base}/v1/public/adoption
"""


@router.get("/.well-known/prama-agent.json")
def manifest():
    return descriptor()


@router.get("/agents.md", response_class=PlainTextResponse)
def guide():
    return execution_guide()


@router.get("/llms.txt", response_class=PlainTextResponse)
def llms():
    d = descriptor()
    return (f"# PRAMA-Dynamagh\nTelegraph-powered machine intelligence. x402 v2; {d['payments']['network']} / {d['payments']['environment']}.\n"
            + ("Base Sepolia.\n" if d['payments']['network'] == "eip155:84532" else "") +
            "Evidence-bound governance and capability-bound Consumer Result. Optional external capability.\n"
            "requested_intent is not necessarily a Telegraph Intent_ID. It is an optional application-level semantic hint.\n"
            "Telegraph performs protocol Intent resolution and Miner selection. PAYMENT != AUTHORITY.\n"
            "Submit query or request; receive live 402, independently validate terms, pay only if authorized.\n"
            "202 returns mandate_id, result_endpoint and a secret one-time-issued result_capability, not final intelligence.\n"
            "GET result_endpoint with X-PRAMA-Result-Capability; inspect consumer_result, evidence, evaluation, decision and ticket.\n"
            "After ambiguous settlement STOP; no automatic payment retry.\n"
            "SUCCEEDED != DELIVERED != SEMANTIC_TASK_FULFILLED; wallet != AgentIdentity. Respect caller authority and spending limits.\n"
            "Semantic task fulfillment is not currently inferred from delivery. WEB_SEARCH is currently a retrieval primitive.\n"
            + "\n".join(f"- {key}: {value}" for key, value in d["discovery"].items() if isinstance(value, str))
            + "\n- Manifest: " + d["interfaces"]["http"]["endpoint"].split("/v1/")[0] + "/.well-known/prama-agent.json\n")
