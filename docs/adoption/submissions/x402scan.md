# x402scan registry pack

PLATFORM: x402scan
STATUS: PLANNED; SIWX-authenticated operator action required
OFFICIAL_URL: https://www.x402scan.com/resources/register
SUBMISSION_METHOD: Official OpenAPI documents POST `/api/x402/registry/register` with `{ "url": "https://prama-dynamagh.up.railway.app/v1/public/ask" }`; writes require SIWX wallet authentication. Register-origin is also available. No wallet signature performed.
CANONICAL_DISCOVERY_URL: https://prama-dynamagh.up.railway.app/v1/public/discovery
CANONICAL_PAID_RESOURCE: POST https://prama-dynamagh.up.railway.app/v1/public/ask
CAPABILITY_URL: https://prama-dynamagh.up.railway.app/v1/public/capabilities
MCP_URL: https://prama-dynamagh.up.railway.app/mcp
TESTNET_DISCLOSURE: x402 v2 exact on Base Sepolia TESTNET; x402scan's current registration materials do not confirm testnet resource support.
TELEGRAPH_ATTRIBUTION: Machine intelligence via Telegraph Protocol; PRAMA-Dynamagh adds evidence-bound evaluation and Consumer Result delivery.
EXACT_PAYLOAD_OR_FORM_VALUES: `{ "url": "https://prama-dynamagh.up.railway.app/v1/public/ask" }`; endpoint-only registration. Its discovery guide accepts the public OpenAPI URL and an unauthenticated 402 challenge with Bazaar input schema.
VERIFICATION_METHOD: After authorized registration, inspect exact resource in the public x402scan catalog and confirm the method, payment rail, and runtime challenge.
POST_SUBMISSION_CHECK: Read-only registry lookup. Registry writes are free according to current OpenAPI but require SIWX; query APIs may be paid.
NOTES: No registration, signature, paid search, or listing status claimed. Source: https://www.x402scan.com/openapi.json and https://github.com/Merit-Systems/x402scan/blob/main/docs/DISCOVERY.md.
