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
Result delivery around acquired intelligence. PRAMA is not a substitute for Telegraph.

## Campaign ledger

Valid status values: PLANNED, SUBMITTED, CRAWLED, LISTED, INDEXED, ROUTABLE, VERIFIED, PENDING, REJECTED, INCOMPATIBLE, INACTIVE.
Dates for planned external actions remain unset until the action occurs.
The initial release published project-owned artifacts. A subsequent operator-reported
Telegraph Discord field report is recorded below; this task sends no messages.

| CAMPAIGN | CHANNEL | CLASSIFICATION | DATE | ACTION | PUBLIC_URL | STATUS | ARTIFACT | NOTES |
|---|---|---|---|---|---|---|---|---|
| v1 | PRAMA public surfaces | MACHINE_DISCOVERY | 2026-09-26 | Deploy and verify discovery and read-only adoption | https://prama-dynamagh.up.railway.app/adoption | VERIFIED | agent-access API + adoption page | HTTP, MCP and unpaid x402 smoke passed |
| v1 | Bazaar resource metadata | MACHINE_DISCOVERY | 2026-09-26 | Verify declared extension against JSON Schema | https://prama-dynamagh.up.railway.app/.well-known/prama-agent.json | VERIFIED | Unpaid HTTP 402 PaymentRequired extension | Declaration only; catalog indexing NOT TESTED |
| v1 | x402 Bazaar | MACHINE_DISCOVERY | 2026-09-26 | Read-only PayAI catalog verification | https://facilitator.payai.network/discovery/search?query=PRAMA-Dynamagh | VERIFIED | ../observations/BAZAAR_DISCOVERY_2026-09-26.md | LISTED / VERIFIED exact canonical resource; dated observation, no new demand/user/agent/wallet counted |
| v1 | Agent402 | DEVELOPER_DISCOVERY | — | Submit directory pack | — | PLANNED | submissions/agent402.md | Machine ingestion unverified |
| v1 | x402 community directories | DEVELOPER_DISCOVERY | — | Identify and submit compatible listing | — | PLANNED | submissions/x402-bazaar.md | Not all directories are machine-native |
| v1 | Run402 | DEVELOPER_DISCOVERY | — | Share integration pack | — | PLANNED | submissions/run402.md | No listing claimed |
| v1 | Hugging Face | DEVELOPER_DISCOVERY | — | Share SmolAgents integration | — | PLANNED | submissions/huggingface.md | No model or Space published |
| v1 | AI Agents List | HUMAN_DISCOVERY | — | Submit human-facing directory entry | — | PLANNED | submissions/aiagentslist.md | Not machine-native |
| v1 | GPT Store | HUMAN_DISCOVERY | — | Assess compatible GPT listing | — | PLANNED | submissions/gpt-store.md | No GPT created or approval claimed |
| v1 | X | HUMAN_DISCOVERY | — | Publish factual adoption post | — | PLANNED | submissions/x-post.md | Draft only |
| v1 | Telegraph Discord | COMMUNITY_ENGAGEMENT | 2026-09-26 | Track 3 real paid M2M field report | NOT_RECORDED | SUBMITTED | ../observations/TELEGRAPH_INTENT_FULFILLMENT_2026-09-26.md | Operator-reported ACKNOWLEDGED; ENGAGEMENT / TECHNICAL FEEDBACK, not adoption counts |

## Claims policy

DO SAY: External M2M Requests; Unique Paying Wallets; Declared Clients;
Registered AgentIdentities; Successful Acquisitions; Admitted Evidence;
Consumer Results Delivered (distinct mandates with evidenced server content delivery).

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
  6 successful acquisitions, 5 admitted evidence records, 1 consumer results delivered.
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

Delivery semantics: Semantic task fulfillment is not currently inferred from delivery.
WEB_SEARCH is currently observed as a search/retrieval primitive, not a research/synthesis workflow.

## Post-live semantic correction and engagement

[Two real execution records and team feedback](../observations/TELEGRAPH_INTENT_FULFILLMENT_2026-09-26.md).
[Independent PayAI Bazaar lookup and baseline evidence](../observations/BAZAAR_DISCOVERY_2026-09-26.md).

Discord outcome: team clarified technical delivery versus semantic task fulfillment
and WEB_SEARCH as a retrieval primitive. Follow-up: RESEARCH_QUERY failure under
investigation; not a confirmed bug. PUBLIC_URL=NOT_RECORDED. This engagement does
not increment request, wallet or agent counts. Earlier NOT_TESTED Bazaar notes
above describe the launch snapshot; the later catalog lookup confirmed indexing.

## Capability discovery alignment — 2026-09-26

The [alignment record](../observations/CAPABILITY_DISCOVERY_V2_ALIGNMENT.md)
supersedes the prior registry-enum interpretation. `/v1/public/capabilities` is
a PRAMA-owned descriptor, not an x402 or Telegraph standard. `requested_intent`
is optional semantic request metadata. Telegraph owns protocol resolution,
eligibility/ranking and Miner selection. WEB_SEARCH remains an example only.
The Bazaar request schema has no Telegraph Intent enum or local registry fetch.
Its null capability example is deliberately non-secret; the initial successful
202 issues the effective private capability once. The result is retrieved by
GET with X-PRAMA-Result-Capability, separately from acceptance.

PayAI search was rechecked read-only: the canonical resource is LISTED / VERIFIED.
That evidence establishes resource discoverability only. Catalog metadata can
lag behind the deployed seller declaration; no payment was made to refresh it.
Discord field-report PUBLISHED / operator-reported ACKNOWLEDGED remains recorded
above, including WEB_SEARCH delivery vs semantic fulfillment and RESEARCH_QUERY
under investigation. No new engagement message or usage event was generated.

## Universal discovery distribution campaign — 2026-09-27

Detailed platform research: [X402_M2M_DISCOVERY_TARGETS_2026-09-27.md](X402_M2M_DISCOVERY_TARGETS_2026-09-27.md).
Canonical descriptor implementation is in review; external checks and listings
below refer to the already deployed paid resource and dated platform evidence.

Each campaign record uses the requested fields. Listing and indexing evidence
are separate from service usage and do not imply M2M demand.

CAMPAIGN: PRAMA-DYNAMAGH-UNIVERSAL-DISCOVERY-2026-09-27
CHANNEL: PayAI Bazaar
DATE: 2026-09-27 (underlying exact-resource observation: 2026-09-26T19:28:03Z)
ACTION: Read-only verification of exact canonical POST resource
PUBLIC_URL: https://facilitator.payai.network/discovery/search?query=PRAMA-Dynamagh
STATUS: VERIFIED
ARTIFACT: observations/BAZAAR_DISCOVERY_2026-09-26.md
EVIDENCE: Exact POST /v1/public/ask resource, x402 v2, Base Sepolia, amount 10000, matching recipient; lastUpdated 2026-09-26T18:12:54.583Z
NOTES: Metadata declaration is current in seller code; catalog metadata refresh is PENDING. No payer enumeration, payment, or demand inference.

CAMPAIGN: PRAMA-DYNAMAGH-UNIVERSAL-DISCOVERY-2026-09-27
CHANNEL: Agent402
DATE: 2026-09-27
ACTION: Read-only official marketplace and submission-flow check
PUBLIC_URL: https://marketplace.agent402.app/marketplace
STATUS: PENDING
ARTIFACT: submissions/agent402.md
EVIDENCE: Search index described seller registration; official marketplace page fetch returned HTTP 410; no current submission or testnet terms confirmed
NOTES: No account flow, authentication, wallet signature, listing, or routing state claimed.

CAMPAIGN: PRAMA-DYNAMAGH-UNIVERSAL-DISCOVERY-2026-09-27
CHANNEL: x402-list
DATE: 2026-09-27
ACTION: Read-only official submission API check; no submit due possible non-refundable Base payment
PUBLIC_URL: https://www.x402-list.com/api
STATUS: PLANNED
ARTIFACT: submissions/x402-list.md
EVIDENCE: API documents HTTP 402 plus $1 USDC Base fee for free-compute hosting; manual review after endpoint probe
NOTES: No email contact supplied and no payment authorized. Base Sepolia acceptance and Railway fee classification remain unverified.

CAMPAIGN: PRAMA-DYNAMAGH-UNIVERSAL-DISCOVERY-2026-09-27
CHANNEL: true402
DATE: 2026-09-27
ACTION: Read-only requirements verification
PUBLIC_URL: https://true402.dev/docs
STATUS: INCOMPATIBLE
ARTIFACT: submissions/true402.md
EVIDENCE: Live documentation reports no testnet; current Base rail is eip155:8453 mainnet and x402 v2
NOTES: No manifest or registration attempted. PRAMA payment architecture remains unchanged.

CAMPAIGN: PRAMA-DYNAMAGH-UNIVERSAL-DISCOVERY-2026-09-27
CHANNEL: x402.new
DATE: 2026-09-27
ACTION: Read-only discovery model check; wait for crawler/index propagation
PUBLIC_URL: https://x402.new/submit
STATUS: PENDING
ARTIFACT: submissions/x402-new.md
EVIDENCE: Official provider guide says directory is Bazaar-derived and has no direct submission form
NOTES: PRAMA uses PayAI; cross-facilitator pickup and exact listing were not confirmed in this check.

CAMPAIGN: PRAMA-DYNAMAGH-UNIVERSAL-DISCOVERY-2026-09-27
CHANNEL: AgentIndex / x402looker
DATE: 2026-09-27
ACTION: Read-only current directory and seller claim flow check
PUBLIC_URL: https://www.agentindex.ai/
STATUS: PLANNED
ARTIFACT: submissions/agentindex.md
EVIDENCE: AgentIndex describes cross-protocol search and brand claim; no official x402looker registration or testnet terms confirmed
NOTES: Manual operator review required before any account-specific claim; no listing or demand claimed.

CAMPAIGN: PRAMA-DYNAMAGH-UNIVERSAL-DISCOVERY-2026-09-27
CHANNEL: x402.direct
DATE: 2026-09-27
ACTION: Read-only directory API and network-compatibility check
PUBLIC_URL: https://x402.direct/docs
STATUS: INCOMPATIBLE
ARTIFACT: submissions/x402-direct.md
EVIDENCE: Directory documents Base-mainnet-only paid search and no seller submission mechanism
NOTES: No search payment or submission performed.

CAMPAIGN: PRAMA-DYNAMAGH-UNIVERSAL-DISCOVERY-2026-09-27
CHANNEL: Run402
DATE: 2026-09-27
ACTION: Read-only product relevance check
PUBLIC_URL: https://docs.run402.com/
STATUS: REJECTED
ARTIFACT: submissions/run402.md
EVIDENCE: Current official docs describe full-stack agent infrastructure, not a third-party x402 discovery directory
NOTES: Platform is active but unrelated to this distribution campaign.

CAMPAIGN: PRAMA-DYNAMAGH-UNIVERSAL-DISCOVERY-2026-09-27
CHANNEL: x402scan (additional)
DATE: 2026-09-27
ACTION: Read-only official registration and network check; manual wallet-auth flow not performed
PUBLIC_URL: https://www.x402scan.com/resources/register
STATUS: PLANNED
ARTIFACT: submissions/x402scan.md
EVIDENCE: Official OpenAPI says registry writes require SIWX; public discovery spec supports OpenAPI and HTTP 402 resource registration
NOTES: No wallet signature or paid query. Base Sepolia indexing acceptance requires operator confirmation.

CAMPAIGN: PRAMA-DYNAMAGH-UNIVERSAL-DISCOVERY-2026-09-27
CHANNEL: EXVIV (additional)
DATE: 2026-09-27
ACTION: Read-only directory observation; paid query not invoked
PUBLIC_URL: https://exviv.com/x402
STATUS: PENDING
ARTIFACT: X402_M2M_DISCOVERY_TARGETS_2026-09-27.md
EVIDENCE: Public directory states provider feed is open; aggregate query is $0.05 USDC on Base
NOTES: No direct seller-listing mechanism identified; retained as a consumer-side WATCH target only.
