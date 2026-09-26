# M2M consumer result contract and local verification

## PostgreSQL certification completed

The existing implementation was certified against local Docker PostgreSQL 16,
using the dedicated `fulfillment_cert` database migrated to
`0032_inbound_x402_result_capability`. Every consumer-result test uses a fresh
database cloned from this migrated template, retaining PostgreSQL constraints
and triggers. Production databases were not used.

Final selection: **101 passed** = **34 Consumer Fulfillment cases on PostgreSQL**
+ **13 existing PostgreSQL integration cases** (evidence provenance, ticket
constraints and ERC8183 evidence constraints) + **54 existing regression cases**.
Existing x402 unit fixtures still use SQLite; they are not represented as
PostgreSQL coverage. PostgreSQL capability coverage comes from the consumer
suite, which exercises the real result endpoint with the migrated schema.

No application behavior changed during certification. Test fixtures were
adapted to flush parent rows before dependent rows and to use the valid ticket
anchor state LOCAL_ONLY. The failed attempts were fixture assumptions exposed
by PostgreSQL, not application regressions. NEW_REGRESSIONS: 0.

DELIVERY_EVENT_SEMANTICS: ONCE_PER_RESPONSE. Eight concurrent authorized GETs
returned content and persisted eight events; the read model still marked only
the two distinct acquisitions DELIVERED. No new acquisition or payment row was
created. A real PostgreSQL CHECK rejection of delivery-event insertion left
the content response successful and created no event, acquisition or payment.
No deadlock was observed in this bounded concurrency test; this is not a claim
that all possible workloads are deadlock-free.

Actual order: capability validation, result construction, closure of the read
session, successful HTTP send, then independent delivery-event transaction.
HTTP_DB_ATOMICITY: FALSE. No writes occur for invalid capabilities.

To reproduce Consumer Fulfillment certification, set DATABASE_URL and
PRAMA_POSTGRES_CERT_URL to the dedicated local fulfillment_cert database and
run `python -m pytest -q -p no:cacheprovider tests/unit/test_m2m_consumer_result.py`.
The test role needs CREATEDB to clone and remove only its per-test databases.
The certification runner blocked Python outbound sockets; PostgreSQL access
was through libpq to the local Docker service. No Telegraph or paid traffic.

The earlier SQLite-only verification record below is retained as history.
Its pending PostgreSQL limitation is resolved by this certification.

## Confirmed representation and cause

`AcquisitionResult.raw_payload` is persisted as `TelegraphCall.raw_response`
by the acquisition worker before normalization. `workers/tasks.py` creates
`Evidence.normalized_payload` with `intent`, `result`, `miner_id`,
`signal_hash`, and `warnings`; `result` comes from the persisted provider
response. AcquisitionResult has no separate intelligence-content attribute.
The old `_x402_result_payload` projected only governance metadata.
Local root cause: **RESULT_PROJECTION_GAP**. No live upstream content was
inspected and this change cannot create missing upstream intelligence.

## Additive response

The original governance envelope is preserved. `consumer_result.results`
contains acquisition_id, requested_intent, evidence_id,
evidence_content_hash, and sanitized content from
`Evidence.normalized_payload["result"]` only.

Both evidence and acquisition must belong to the authorized mandate.
Evidence must be ADMITTED and provenance VERIFIED, matching the existing
Telegraph admission contract. LIMITED/REJECTED/unverified evidence is excluded.
Multiple acquisitions retain their own evidence/content correspondence.
There is no provider-response fallback, payment replay, or new acquisition.

* DELIVERED: this response actually includes at least one nonempty sanitized
  admitted result. It is not a claim that every acquisition is fulfilled or
  that the consumer's question was answered correctly. Individual results and
  existing acquisitions identify partial delivery.
* PENDING: no deliverable content yet and mandate is nonterminal, including
  DECIDED while ticketing may still complete.
* NOT_AVAILABLE: no deliverable content and mandate is TICKETED or FAILED.

Empty nested values or redaction-only output do not count as intelligence.
Zero and false remain valid result values. No Evidence or Ticket hashes are
recomputed, relabeled or mutated. The existing evidence digest implementation
uses keccak256; no new algorithm assertion is attached to arbitrary rows.

## Disclosure boundary and sanitization

Only X-PRAMA-Result-Capability authorizes the public result endpoint. Missing,
wrong and cross-mandate capabilities retain the existing 404 response.
Bearer is not a substitute. The generic evidence endpoint denies M2M with
403 regardless of headers. Existing USER/AUTONOMOUS behavior is preserved.

Recursive projection removes credential, signature, capability, cookie,
header, raw response, private transport and database-credential fields.
It also redacts configured secret values, the supplied capability, Bearer
strings, private-key PEM blocks and recognizable credential assignments/URLs.
Ordinary URLs, documents, prices and weather values are retained.
This is defensive sanitization of structured evidence; it does not establish
that arbitrary unlabeled prose could never contain an unrecognizable secret.

## Delivery accounting

The existing UsageEvent table is reused, with no migration. After the final
successful ASGI send, ConsumerResultResponse appends one event per delivered
response: M2M_CONSUMER_RESULT_DELIVERED. It includes mandate_id, created_at,
origin=M2M, acquisition_ids, evidence_ids, delivery_surface=x402-public-result
and delivery_scope=SERVER_DELIVERY_CONFIRMED. It stores neither content nor
capability/signature/credential material. Repeat GETs append repeat delivery
observations; count distinct mandate/acquisition IDs for adoption metrics.

This means server transport accepted the response, not consumer acknowledgment,
understanding or content correctness. A failed send creates no event. Send and
commit are not atomic: commit failure is logged with a constant code, and does
not invent a receipt or turn an already sent response into an error.

History derives DELIVERED per mandate/acquisition only from persisted delivery
events. Otherwise it remains UNKNOWN. NOT_DELIVERED is deliberately not inferred
because historical deliveries or failed receipt commits cannot be excluded.

## Verification

From backend, with installed dependencies (no package downloads):

```powershell
python tests/offline_runner.py -q tests/unit/test_m2m_consumer_result.py tests/unit/test_x402_public.py tests/unit/test_x402_seller_convergence.py tests/unit/test_m2m_rail.py tests/unit/test_public_surfaces.py tests/unit/test_user_auth.py tests/unit/test_o_evidence_provenance_contract.py tests/unit/test_erc8183_evidence.py tests/unit/test_acquisition_resource_contract.py --tb=short
```

Result: **86 passed**, including **32 new fulfillment tests/cases** and 54
existing regression cases. Eleven SQLite date-adapter deprecation warnings.
The new suite exercises the real API, SQLAlchemy persistence, capability
checks, response sending and delivery history using isolated SQLite databases.
It includes send failure, receipt-commit failure, multiple acquisitions,
cross-mandate associations, sanitized-only results and governance preservation.

The runner blocks outbound socket connections and DNS. Windows asyncio's
internal socketpair self-pipe is allowed, not application network traffic.
It forces an isolated SQLite URL; it never uses a configured external database.

Failure classification:

* ENVIRONMENTAL, resolved: Windows sandbox ACL denied temporary SQLite files;
  rerun with normal local permissions passed.
* PREEXISTING test isolation issue, resolved: M2M auth-only test queried the
  global ownership dependency's external DB; the test now supplies an empty
  mandate lookup without changing application auth.
* ENVIRONMENTAL, outstanding: attempted existing PostgreSQL integration tests
  `test_o_evidence_provenance.py` and `test_ticket_constraints.py` with maxfail=1.
  The autouse fixture failed before the first test: SQLite has no provisioned
  evidence table. These suites require a migrated PostgreSQL test database;
  they are **not certified** by the SQLite tests.
* NEW_REGRESSION: 0 observed in the final executed regression set.

`git diff --check`: passed. No migrations, external requests, Telegraph calls,
payments or deployment. User edits outside this change were preserved.

Implementation is locally verified; full certification and readiness for a
real paid M2M validation remain pending PostgreSQL integration validation and
the separately authorized deployment phase.
