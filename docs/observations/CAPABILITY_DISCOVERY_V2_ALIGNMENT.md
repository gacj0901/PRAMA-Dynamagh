# Capability discovery / Telegraph V2 alignment — 2026-09-26

## Baseline

- BASELINE_COMMIT: `61ab1d4fc456695f13a4004dbb2ebb9f9e1ba7f3`; main matched origin/main.
- WORKTREE_CLEAN: NO. Existing changes in AGENTS.md, the Telegraph audit,
  competition-workflows.md, track3-state-reconstruction.md, frontend/index.html
  and frontend/src/main.tsx are preserved outside this commit. Only an additive
  audit note is staged from that file.
- ALEMBIC_HEAD: `0032_inbound_x402_result_capability`. No migration is added.
- BASELINE_TESTS: 93 PASS / 0 FAIL before edits (25 discovery, 68 regressions).
- Historical adoption commits `42772c2`, `67cbaed` exist; neither is HEAD.
- Baseline Railway API/frontend: SUCCESS at `61ab1d4`; worker: SUCCESS at
  `67cbaed60a300f82513fd87a235c41788fce6bdb`.

## Correct boundary and observable contract

`requested_intent` / legacy `intent` are optional application semantic hints,
not necessarily Telegraph Intent_IDs. Telegraph owns resolution, eligibility,
ranking and Miner selection. PRAMA owns Mandate, constraints, Evidence,
provenance, structural evaluation, authority, Decision, Ticket and result delivery.

Removed the previous local provider-registry projection, provider lookup at
discovery/challenge time, and both request-field enums. Its raw 133-name snapshot
was removed; the historical commit remains available. There is no public intents
endpoint and no alternate paid endpoint. `/v1/public/capabilities` is a PRAMA-owned,
public read-only descriptor, cacheable for 60 seconds, without provider/DB calls.
Manifest and MCP reference/use the same descriptor. MCP tool names and transport
remain unchanged. The paid route and runtime validation are unchanged.

The actual public API requires a nonempty string in `query` or `request`.
A truthy `request` takes precedence; `intent` takes precedence when present,
including null. Hints may be strings or null. Arbitrary client constraints are
not consumed here: the server constructs constraints and budget. Discovery
therefore does not advertise a client constraints input. WEB_SEARCH is an example
only; no routing guarantee or guessed replacement for RESEARCH_QUERY is offered.

The Bazaar JSON Schema retains the existing v2 HTTP body extension shape.
Existing top-level resource serviceName/tags are left unchanged; compatibility
was established in [the prior specification audit](BAZAAR_DISCOVERY_2026-09-26.md).
Live 402 terms remain authoritative. A successful initial paid POST returns 202
with mandate_id, result_endpoint and a one-time-issued secret result_capability;
it is acceptance, not final intelligence. The safe discovery capability example
is null. Idempotent replay does not reissue the capability. GET the returned URL
with X-PRAMA-Result-Capability to inspect consumer_result, evidence, evaluation,
decision and ticket. Ambiguous settlement must not trigger another authorization.

## Evidence for dated examples

Read-only production SQL, limited to aggregates of persisted M2M acquisitions,
observed: FINANCIAL_DATA / SUCCEEDED = 1; WEB_SEARCH / SUCCEEDED = 2;
RESEARCH_QUERY / FAILED = 2. No acquisition/payment was created by inspection.
These are observations, not protocol support assertions or future guarantees.

- WEB_SEARCH: OBSERVED_SUCCESS. The operator-supplied execution
  `742b0c6a-e962-43b5-99d6-74d45bc8cb70` had admitted, verified evidence and a
  delivered result. Semantic task fulfillment was NOT_ESTABLISHED; WEB_SEARCH
  is a retrieval/search primitive. See [the execution record](TELEGRAPH_INTENT_FULFILLMENT_2026-09-26.md).
- FINANCIAL_DATA: OBSERVED_SUCCESS at acquisition level only; this inspection
  does not certify semantic content.
- WEATHER_FORECAST: UNVERIFIED. The KIMI case remains operator-attested; complete
  persisted lineage was not independently matched. It is not counted as a new
  observed success or inserted into metrics.
- RESEARCH_QUERY: FAILED / TELEGRAPH_REQUEST_FAILED; operator-reported external
  status UNDER_INVESTIGATION. No inference of nonexistence, permanent routing
  failure, PRAMA defect, or replacement Intent.

PAYMENT != AUTHORITY. DELIVERED != SEMANTIC_TASK_FULFILLMENT.
The metric remains Consumer Results Delivered, not semantic fulfillment.
Catalog indexing and integration status are separate from usage counters.

## PayAI read-only discovery

[Exact-resource search](https://facilitator.payai.network/discovery/search?query=PRAMA-Dynamagh)
returned HTTP 200, partialResults=false and one exact canonical resource match
before this correction. Catalog lastUpdated was `2026-09-26T18:12:54.583Z`;
Bazaar extension present, serviceName null. This confirms listing/discoverability,
not propagation of the new metadata, external demand, a user/agent/wallet, or
semantic fulfillment. No verify/settle call or paid traffic was used to refresh it.

## Historical audit

No physical agent meta-trace matching the reported examples was found.
No substantive historical finding is rewritten. A dated POST-AUDIT
IMPLEMENTATION NOTE cites `30e981c398db416b3b533609d984f973a7138521`, implementation
locations and the existing seven-case PostgreSQL authority-race certification.
No ExecutionPermit, G12/G13, origin, settlement, kernel or worker code is changed.
Post-commit/pre-dispatch recovery and DB/network atomicity limitations remain.

## Validation and deployment scope

Targeted: 26 PASS / 0 FAIL. Relevant regression: 101 PASS / 0 FAIL.
An initial new-test import failure (requests is not installed) was corrected to
use the standard-library socket guard; the targeted selection then passed.
Tests ran in an isolated Docker/PostgreSQL environment with outbound Python
connections blocked. Existing pytest asyncio_mode and SQLite date warnings remain.
Regression covers x402, M2M rail, consumer result, origin scope, user auth,
provenance, resource contracts and PostgreSQL evidence/ticket constraints.

Only API and frontend are affected. Deployment is from the explicit Git commit,
excluding unrelated local edits. Production verification requires the six public
GET surfaces, MCP initialize/list/discovery and exactly one unsigned POST yielding
402. No signer, private capability retrieval, paid request or new USDC spend is
part of validation. Final deployment/smoke outcomes are reported separately.
