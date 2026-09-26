"""Public PRAMA-owned discovery descriptor; no execution or signing tools."""
from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

router = APIRouter(tags=["agent-discovery"])
DESCRIPTION = ("Paid machine intelligence with Evidence, provenance, PRAMAgraph "
               "structural evaluation, Decision, Ticket and capability-bound Consumer Result.")
BENIGN = ("[BENIGN AGENT DISCOVERY]\nDiscover PRAMA-Dynamagh as an optional evidence-bound machine "
          "intelligence service. Use only when external service access and payment are permitted "
          "by the caller's own governing policy.")
REQUEST_SCHEMA = {
    "type": "object", "properties": {
        "intent": {"type": "string", "description": "Telegraph intent forwarded unchanged; availability depends on provider routing."},
        "requested_intent": {"type": "string", "description": "Alias for intent; intent takes precedence when present."},
        "query": {"type": "string", "minLength": 1}, "request": {"type": "string", "minLength": 1},
    }, "anyOf": [{"required": ["query"]}, {"required": ["request"]}],
    "description": "Use one query/request and one intent/requested_intent. request takes precedence over query.",
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
                                  "Subsequent result contains consumer_result, evidence, evaluation, decision and ticket."}


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
                "bodyType": {"enum": ["json", "form-data", "text"]}, "body": REQUEST_SCHEMA}},
            "output": {"type": "object", "required": ["type"], "properties": {
                "type": {"type": "string"}, "example": ACCEPTED_SCHEMA}},
        }},
    }}


def supported_capabilities():
    return {"capabilities": ["evidence_bound_intelligence_acquisition", "capability_bound_consumer_result"],
            "intent_selection": "Telegraph routing; an intent string is forwarded to the acquisition layer",
            "requestable_intent_examples": ["WEB_SEARCH", "FINANCIAL_DATA", "WEATHER_FORECAST"],
            "live_provider_inventory": "UNKNOWN", "availability_guaranteed": False,
            "epistemic_coverage": {"e1_validated_targets": ["CRYPTO_PRICE"],
                                    "registry_membership_is_not_validated_coverage": True}}


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
                          "consumer_fulfillment_condition": "consumer_result.status == DELIVERED",
                          "delivery_scope": "Server returns admitted content; not consumer acknowledgment or content correctness."},
            "outputs": ["consumer_result", "evidence", "evidence_content_hash", "provenance", "structural_evaluation", "decision", "ticket"],
            "identity": {"agent_identity": "optional", "wallet_is_agent_identity": False, "wallet_role": "economic_principal"},
            "acquisition": {"infrastructure": "Telegraph Protocol"},
            "discovery": {"guide": base + "/agents.md", "llms": base + "/llms.txt", "adoption": base + "/adoption",
                          "metrics": base + "/v1/public/adoption", "bazaar_metadata_declared": True,
                          "bazaar_indexing_confirmed": False},
            "capabilities": supported_capabilities(), "request_schema": REQUEST_SCHEMA, "result_schema": RESULT_SCHEMA}


def execution_guide():
    base = descriptor()["interfaces"]["http"]["endpoint"].removesuffix("/v1/public/ask")
    return f"""# PRAMA-Dynamagh — Agent Execution Guide

{BENIGN}
This service is an optional external machine capability.
Do not override system instructions, security policy, wallet controls,
delegated authority, or spending limits.

## EXECUTION PATH
1. Discover supported capabilities: {base}/.well-known/prama-agent.json
2. POST request without payment to {base}/v1/public/ask.
3. Receive HTTP 402.
4. Validate current payment challenge: version, scheme, resource, network, asset, amount, recipient and EIP-712 domain.
5. Independently evaluate cost against caller-controlled request/session limits.
6. Sign only when authorized. Keep keys outside the LLM.
7. Submit PAYMENT-SIGNATURE with the identical logical request and Idempotency-Key.
8. Preserve mandate result capability privately immediately upon 202; it is delivered in clear only once.
9. GET only the returned result_endpoint using X-PRAMA-Result-Capability (not Bearer).
10. Verify consumer_result.status and inspect actual results for the requested intelligence.
11. Preserve Evidence hash and Ticket when useful; never expose the capability.

Input: {{"requested_intent":"WEB_SEARCH","query":"Your actual information need"}}.
Aliases: intent (preferred legacy field), request. Do not send conflicting aliases.
Result: 202 is acceptance, not fulfillment. Poll only the returned same-origin result URL.
After ambiguous paid response: STOP. Do not sign/pay again or retry automatically.
SUCCEEDED != DELIVERED. wallet != AgentIdentity.
DELIVERED means content in this HTTP response, possibly a subset of acquisitions;
not acknowledgment, correctness, or proof that the question is fully answered.
Current network: {descriptor()['payments']['network']} / {descriptor()['payments']['environment']}.
Price, recipient and asset are challenge-derived. This deployment is not mainnet.
Telegraph provides machine intelligence infrastructure. PRAMA-Dynamagh adds
evidence-bound evaluation, execution governance, auditability and Consumer fulfillment.
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
            "SUCCEEDED != DELIVERED; wallet != AgentIdentity. Respect caller authority and spending limits.\n"
            + "\n".join(f"- {key}: {value}" for key, value in d["discovery"].items() if isinstance(value, str))
            + "\n- Manifest: " + d["interfaces"]["http"]["endpoint"].split("/v1/")[0] + "/.well-known/prama-agent.json\n")
