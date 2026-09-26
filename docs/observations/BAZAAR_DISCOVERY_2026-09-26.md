# Bazaar discovery verification — 2026-09-26

## Baseline

BASELINE_COMMIT: 67cbaed60a300f82513fd87a235c41788fce6bdb (main equals origin/main).
WORKTREE_CLEAN: NO. Preserved unrelated edits in AGENTS.md,
docs/competition-workflows.md, docs/track3-state-reconstruction.md,
frontend/index.html and frontend/src/main.tsx.
ALEMBIC_HEAD: 0032_inbound_x402_result_capability.
TEST_BASELINE: 81 PASS / 0 FAIL, before changes; isolated Docker and local PostgreSQL.
No migration or payment was required.

## Implementation and standards

Runtime API configuration confirms PayAI, public base URL
https://facilitator.payai.network, x402 v2, eip155:84532.
Inbound seller is custom Python wire implementation. Installed repository
gateway packages @x402/core, @x402/evm and @x402/fetch are 2.25.0; package.json
declares ^2.0.0, so local installation is not proof of the remote gateway version.
No dependency upgrade or gateway deployment is needed for this correction.

Compared against current official sources:

* [x402 Foundation v2](https://github.com/x402-foundation/x402/blob/main/specs/x402-specification-v2.md)
* [Bazaar extension](https://github.com/x402-foundation/x402/blob/main/specs/extensions/bazaar.md)
* [PayAI discovery API](https://docs.payai.network/x402/facilitators/bazaar)

The live unsigned challenge validates against its Draft 2020-12 Bazaar schema,
including POST JSON input and 202 acceptance output. Subsequent capability GET
result is a separate schema. Existing exact payment requirements remain unchanged:
10000 atomic USDC, Base Sepolia, resource `/v1/public/ask`, USDC EIP-712 domain / 2.
The custom requirements retain legacy resource/description/mimeType fields;
the canonical v2 resource object is top-level. No settlement semantics changed.

Installed core ResourceInfoSchema supports serviceName/tags. The correction adds
`PRAMA-Dynamagh` and five printable ASCII tags to the top-level resource only:
ai-agents, intelligence, evidence, governance, telegraph. Existing catalog entry
had null serviceName/tags: publishing metadata does not retroactively refresh it.

## Read-only catalog observation

Observed 2026-09-26 at approximately 19:28 UTC. Exact resource:
https://prama-dynamagh.up.railway.app/v1/public/ask

| Query | HTTP | Exhaustion/result |
|---|---|---|
| /discovery/resources?payTo=0xC92b5ec74dca3EeE0A615dE026C3F3756cd18FB6&limit=1000&offset=0 | 200 | 1 item / total 1; exact resource found |
| /discovery/resources?network=eip155:84532&scheme=exact&extensions=bazaar&limit=1000&offset=0 | 200 | 41 items / total 41; exact resource found |
| /discovery/search?query=https%3A%2F%2Fprama-dynamagh.up.railway.app%2Fv1%2Fpublic%2Fask&limit=50 | 200 | Exact resource; partialResults=false |
| /discovery/search?query=PRAMA-Dynamagh&limit=50 | 200 | Exact resource; partialResults=false |
| /discovery/listing-status?resource=https%3A%2F%2Fprama-dynamagh.up.railway.app%2Fv1%2Fpublic%2Fask | 200 | listed=true; hidden=false |

Pagination used limit/offset and stopped only after reaching reported total.
Only matching resource data and aggregate lookup counts were retained; no payer
enumeration. Search is corroboration, not an exhaustive absence claim.

Catalog: type=http, method=POST, x402Version=2; exact Base Sepolia USDC terms
match the live challenge, including 10000 amount and configured recipient.
lastUpdated=2026-09-26T18:12:54.583Z.
listing-status lastWrite: updated, source=settle, at=2026-09-26T18:12:54.598Z.

BAZAAR_METADATA_DECLARED: YES.
BAZAAR_METADATA_SCHEMA_VALID: YES.
BAZAAR_RESOURCE_FOUND_IN_DISCOVERY: YES.
BAZAAR_INDEXING_CONFIRMED: YES, as of this observation, not a perpetual guarantee.
BAZAAR_EXTENSION_RESPONSE: NOT_OBSERVED.
BAZAAR_REJECTION_REASON: NONE.

The seller's `_facilitator` reads JSON body only and discards response headers.
The persisted settlement_reference is truncated to 255 characters and is not
a header archive. No historical EXTENSION-RESPONSES can be inferred from this
implementation or the catalog's lastWrite. Its absence is not rejection.
No new payment or verify/settle request was made to obtain a header.

Public indexing status includes the dated observation and reference, and falls
back to INDETERMINATE if resource/facilitator/network/recipient configuration no
longer matches. It does not derive confirmation from extensions.bazaar.

Read-only inspection of the existing payment for mandate
742b0c6a-e962-43b5-99d6-74d45bc8cb70 confirmed a SETTLED record; its persisted
settlement_reference was not complete JSON and contained no archived extension
header. Only these boolean/status findings were emitted, never the raw record.

## Correction validation and release scope

TARGETED_TESTS: 19 PASS / 0 FAIL. REGRESSION_TESTS: 101 PASS / 0 FAIL.
The selection includes real local PostgreSQL constraints, unchanged delivery
event, USER/M2M/AUTONOMOUS origin scope, MCP and unsigned x402 behavior.
Provider resource metadata also passed installed @x402/core 2.25.0
ResourceInfoSchema parsing. No migration, kernel or worker code changed.
Release scope: API and frontend only; worker autodeploy temporarily disabled
for the main push and restored afterward. Post-deploy checks are read-only,
plus one unsigned challenge; no signed payment or settlement retry.
