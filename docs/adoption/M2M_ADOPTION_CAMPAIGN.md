# PRAMA-DYNAMAGH — M2M ADOPTION & AGENT ACCESS CAMPAIGN v1

Provider: AptadinamiK Cybernetics. Payment environment: Base Sepolia TESTNET.
This ledger records observable work, not synthetic users, wallets or requests.

## Public framing

DISCOVERABLE → MACHINE-READABLE → x402 PAYABLE → TELEGRAPH-POWERED →
EVIDENCE-BOUND → GOVERNED → AUDITABLE → CONSUMER-DELIVERED.

Agent → Discovery → PRAMA Agent Access (native HTTP/x402, discovery MCP,
machine manifests, shared client examples) → M2M Mandate → AcquisitionTask →
Telegraph / Miner → Evidence → PRAMAgraph → Decision → Ticket → Consumer Result.

Telegraph provides machine intelligence infrastructure. PRAMA-Dynamagh adds
evidence-bound evaluation, execution governance, auditability and Consumer
fulfillment around acquired intelligence. PRAMA is not a substitute for Telegraph.

## Campaign ledger

Valid status values: PLANNED, SUBMITTED, LISTED, PUBLISHED, VERIFIED, REJECTED.
Dates for planned external actions remain unset until the action occurs.
Only project-owned artifacts are published by this release; no community
message or directory submission is authorized or represented as performed.

| CAMPAIGN | CHANNEL | CLASSIFICATION | DATE | ACTION | PUBLIC_URL | STATUS | ARTIFACT | NOTES |
|---|---|---|---|---|---|---|---|---|
| v1 | PRAMA public surfaces | MACHINE_DISCOVERY | 2026-09-26 | Deploy and verify discovery and read-only adoption | https://prama-dynamagh.up.railway.app/adoption | VERIFIED | agent-access API + adoption page | HTTP, MCP and unpaid x402 smoke passed |
| v1 | Bazaar resource metadata | MACHINE_DISCOVERY | 2026-09-26 | Verify declared extension against JSON Schema | https://prama-dynamagh.up.railway.app/.well-known/prama-agent.json | VERIFIED | Unpaid HTTP 402 PaymentRequired extension | Declaration only; catalog indexing NOT TESTED |
| v1 | x402 Bazaar | MACHINE_DISCOVERY | — | Declare extension; verify facilitator indexing separately | — | PLANNED | submissions/x402-bazaar.md | Declared metadata does not prove catalog indexing |
| v1 | Agent402 | DEVELOPER_DISCOVERY | — | Submit directory pack | — | PLANNED | submissions/agent402.md | Machine ingestion unverified |
| v1 | x402 community directories | DEVELOPER_DISCOVERY | — | Identify and submit compatible listing | — | PLANNED | submissions/x402-bazaar.md | Not all directories are machine-native |
| v1 | Run402 | DEVELOPER_DISCOVERY | — | Share integration pack | — | PLANNED | submissions/run402.md | No listing claimed |
| v1 | Hugging Face | DEVELOPER_DISCOVERY | — | Share SmolAgents integration | — | PLANNED | submissions/huggingface.md | No model or Space published |
| v1 | AI Agents List | HUMAN_DISCOVERY | — | Submit human-facing directory entry | — | PLANNED | submissions/aiagentslist.md | Not machine-native |
| v1 | GPT Store | HUMAN_DISCOVERY | — | Assess compatible GPT listing | — | PLANNED | submissions/gpt-store.md | No GPT created or approval claimed |
| v1 | X | HUMAN_DISCOVERY | — | Publish factual adoption post | — | PLANNED | submissions/x-post.md | Draft only |
| v1 | Telegraph Discord | COMMUNITY_ENGAGEMENT | — | Share Track 3 evidence | — | PLANNED | submissions/telegraph-discord.md | Draft only |

## Claims policy

DO SAY: External M2M Requests; Unique Paying Wallets; Declared Clients;
Registered AgentIdentities; Successful Acquisitions; Admitted Evidence;
Consumer Fulfilled (distinct mandates with evidenced server content delivery).

DO NOT SAY unless independently established: Unique independent agents;
Unique users; Production mainnet revenue; 87% risk reduction; standard safety
requirement; agents are required to use PRAMA.

Wallets, declared labels, identity records and requests measure different
things. Polling deliveries are deduplicated by mandate. DELIVERED does not
mean every acquisition completed, the consumer acknowledged, or the content
answered its question correctly. No raw payer list is public.

## Verified execution proof and attribution

Operator-supplied certified case: KIMI_EXTERNAL, WEATHER_FORECAST, 0.01 USDC,
SUCCEEDED acquisition, ADMITTED evidence, VERIFIED provenance, PERMIT decision,
DELIVERED Consumer Result. Hash:
`0xed49ace56b0e3742b6cb4c1c19955ed77deff9075dd89bc4937954a1dec9d74f`.

The public JSON checks the matching persisted lineage and delivery event.
Until that match is present it explicitly reports OPERATOR_ATTESTED; a supplied
claim never increments a metric. No receipt capability, signature or secret is
published. KIMI_EXTERNAL is a declared client label, not verified independent
identity. This release performs no paid validation.

## TELEGRAPH TRACK 3 — ADOPTION / ENGAGEMENT EVIDENCE

* PRAMA-Dynamagh is deployed; the preceding Consumer Fulfillment release was
  certified and deployed as `819945cec07a42363a100974daa089407b80bb22`.
* Its canonical worker uses live Telegraph acquisition infrastructure.
* The supplied certified case attests external x402 M2M activity, a successful
  paid acquisition and production Consumer Fulfillment. Public counters and
  proof verification must be checked at the linked adoption surface.
* Evidence is persisted and hashed. Governance and delivery remain distinct.
* Public machine discovery, remote MCP, Bazaar declaration and adoption metrics
  are deployed and smoke-verified; observations are recorded below.
* Directory/community packs and Python/TypeScript client examples were produced.
  Preparing these artifacts is completed adoption work, not evidence of external
  submissions, listings or community engagement responses.

## Specification and compatibility evidence

The backend previously had no MCP SDK dependency; its outbound MCP adapter is
a separate hand-written client, not the public server. Public discovery pins
the official Python SDK `mcp==2.2.0`, using Streamable HTTP with stateless legacy
sessions and JSON responses. MCP performs no signing or paid request.

The Python inbound x402 seller is custom v2 wire code; the gateway declares
`@x402/core`, `@x402/evm`, `@x402/fetch` ^2.0.0. Bazaar is an additive top-level
PaymentRequired extension (`info` plus a JSON Schema validating that info),
following the official HTTP POST/body builder. Payment requirements, price,
verification and settlement functions are unchanged. The 202 acceptance schema
is distinguished from the later capability GET result schema. Indexing is not
tested and no facilitator settlement is invoked during this campaign.

Primary references:
* https://github.com/modelcontextprotocol/python-sdk/tree/v2.2.0
* https://py.sdk.modelcontextprotocol.io/
* https://docs.x402.org/extensions/bazaar
* https://github.com/coinbase/x402/blob/main/typescript/packages/extensions/src/bazaar/http/resourceService.ts

`requested_intent` is an additive alias for the canonical `intent` request field;
the existing field retains precedence. Intent routing and miner selection are
unchanged. Examples are not an exhaustive live provider capability inventory.
OpenAPI includes the native paid entrypoint and capability result endpoint.

## Deployment verification

Observed on 2026-09-26, approximately 16:52–16:54 UTC, for launch commit
`42772c2405018e7d7258f391503efe47ee3d7fcd`. Railway API, worker and frontend all
reported SUCCESS on that commit.

* GET `/`, `/adoption`, `/v1/public/adoption`, `/.well-known/prama-agent.json`,
  `/agents.md`, `/llms.txt`, `/openapi.json`: HTTP 200 after API rollout completed.
* Adoption JSON: `Cache-Control: public, max-age=30`; aggregate counts only.
* MCP `/mcp`: initialize, tools/list and prama.discover returned HTTP 200 with
  valid JSON-RPC results. All three intended discovery tools were listed.
* Exactly one unsigned POST `/v1/public/ask`: HTTP 402, x402 v2 exact,
  `eip155:84532`, 10000 atomic USDC (0.01), expected USDC contract and recipient,
  EIP-712 USDC / 2, exact canonical resource URL. Bazaar info validated against
  its JSON Schema. No authorization was generated or submitted.
* Persisted snapshot: 7 external M2M requests, 6 settled requests, 2 paying
  wallets, 2 declared client labels, 2 registered M2M identity records,
  6 successful acquisitions, 5 admitted evidence records, 1 consumer fulfilled.
  These are observed counts at that time, not permanent totals or independent
  agent/user estimates.
* KIMI proof verification returned **OPERATOR_ATTESTED**, not
  PERSISTED_LINEAGE_VERIFIED. The supplied certified case is visible and
  sanitized, but this campaign did not independently confirm its entire
  persisted lineage. It is never inserted into or added to aggregate metrics.
* Bazaar catalog indexing: NOT TESTED. External submissions remain PLANNED.

No paid traffic, artificial users, synthetic wallets or invented AgentIdentities.

## Local validation

Backend: **112 passed**, comprising 11 new agent-access cases and 101 relevant
regression cases, including PostgreSQL Consumer Fulfillment and evidence/ticket
checks, using the freshly built backend Docker image and local test database.
No new regressions were observed in this selection.

Backend selection includes discovery documents, MCP initialize/tools-list/all
three discovery tools, JSON Schema validation of Bazaar info, unchanged payment
requirements, request alias forwarding, persisted aggregate counts, no wallet
enumeration and polling deduplication. It also includes the existing x402,
Consumer Fulfillment and PostgreSQL evidence/ticket regression suites.
Python example: 9 offline tests. TypeScript example: strict typecheck and 8
offline tests. Signers/transports in tests are isolated doubles, not service
traffic or campaign activity. Nginx configuration passes nginx -t without network.
The only supported economic path remains native HTTP/x402.
