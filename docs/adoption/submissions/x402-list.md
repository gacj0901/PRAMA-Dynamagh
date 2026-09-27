# x402-list submission pack

PLATFORM: x402-list
STATUS: PLANNED; submission withheld because the live API may require a non-refundable Base payment for free-compute hosting
OFFICIAL_URL: https://www.x402-list.com/api
SUBMISSION_METHOD: POST https://x402-list.com/api/v1/submit; API returns a live x402 challenge when a listing fee applies, followed by human review
CANONICAL_DISCOVERY_URL: https://prama-dynamagh.up.railway.app/v1/public/discovery
CANONICAL_PAID_RESOURCE: POST https://prama-dynamagh.up.railway.app/v1/public/ask
CAPABILITY_URL: https://prama-dynamagh.up.railway.app/v1/public/capabilities
MCP_URL: https://prama-dynamagh.up.railway.app/mcp
TESTNET_DISCLOSURE: Service accepts x402 v2 exact on Base Sepolia testnet; listing site's fee, if applied, is on Base mainnet and is not authorized.
TELEGRAPH_ATTRIBUTION: Machine intelligence via Telegraph Protocol; PRAMA-Dynamagh adds evidence-bound governance and Consumer Result delivery.
EXACT_PAYLOAD_OR_FORM_VALUES:

```json
{
  "url": "https://prama-dynamagh.up.railway.app",
  "email": "<operator contact email required>",
  "service_name": "PRAMA-Dynamagh",
  "description": "Evidence-bound machine intelligence via Telegraph Protocol with PRAMAgraph evaluation and capability-bound Consumer Result delivery.",
  "website_url": "https://prama-dynamagh.up.railway.app",
  "category": "AI",
  "endpoints": ["POST /v1/public/ask"],
  "notes": "Machine discovery: https://prama-dynamagh.up.railway.app/v1/public/discovery. Base Sepolia testnet only."
}
```

VERIFICATION_METHOD: Recheck the public service API by name and canonical URL; confirm the endpoint probe and human approval independently.
POST_SUBMISSION_CHECK: Only after an operator supplies contact email and confirms any payment challenge is not paid. Track submission ID, probe, review, and listing separately.
NOTES: Official docs state a one-time $1 USDC Base payment for services on free compute hosts. Railway classification and Base Sepolia directory support were not explicitly specified. No API request was posted.
