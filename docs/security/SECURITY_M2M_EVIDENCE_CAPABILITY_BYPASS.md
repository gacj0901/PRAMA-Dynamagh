# Security Finding: Potential M2M Evidence Capability Bypass

## Local remediation — consumer fulfillment release

`LOCAL_CODE_STATUS: CLOSED`

`PRODUCTION_STATUS: NOT_VERIFIED / NOT_DEPLOYED`

The generic evidence endpoint now denies every M2M-origin mandate with HTTP
403, including requests carrying a Bearer or a result capability. M2M content
is served only by the mandate-scoped public result endpoint after its existing
capability validation. USER ownership checks and AUTONOMOUS behavior are
unchanged. No capability is accepted on the generic evidence endpoint.

Regression coverage lives in `backend/tests/unit/test_m2m_consumer_result.py`:
missing/wrong/cross-mandate capability, generic evidence denial, cross-mandate
evidence isolation, USER owner/non-owner and AUTONOMOUS compatibility.
See `../M2M_CONSUMER_FULFILLMENT.md` for verification and outstanding PostgreSQL
integration certification. The original finding below is retained as history;
its descriptions of vulnerable behavior refer to the code before this fix.

## Classification

```text
CODE_LEVEL_FINDING: CONFIRMED
PRODUCTION_EXPLOITABILITY: NOT_VERIFIED
```

This finding records a code-level authorization inconsistency. It does not
assert that a third party accessed production Evidence or that the affected
code is currently deployed.

## Severity

**Proposed severity: Medium.** The endpoint returns the full normalized
Evidence payload without requiring a mandate-scoped principal for M2M-origin
mandates. The documented precondition is knowledge of the mandate ID, which
is an opaque identifier and reduces casual discovery, but an ID is not an
authorization credential and may be disclosed through client records, logs,
or other artifacts. The actual sensitivity of payloads and production
exposure have not been verified; severity should be revisited after those
checks.

## Affected surface

- **Affected endpoint:** `GET /v1/mandates/{mandate_id}/evidence`
- **Affected origin:** `M2M`
- **Potential disclosure:** `Evidence.normalized_payload`
- **Attack precondition:** knowledge of `mandate_id`

## Proven code path

1. [`app/main.py`](../../backend/app/main.py) installs
   `protect_user_artifact` as a global FastAPI dependency.
2. [`app/users/auth.py`](../../backend/app/users/auth.py) loads the mandate
   from the route's `mandate_id`. It requires a user session only when
   `mandate.origin == "USER"`; other origins return without equivalent
   authorization.
3. [`app/api/mandates.py`](../../backend/app/api/mandates.py) defines the
   affected evidence route with only a database-session dependency. It queries
   Evidence by `mandate_id` and serializes `normalized_payload` in the
   response.
4. The inbound x402 M2M flow separately issues an
   `X-PRAMA-Result-Capability`, and
   [`app/api/x402.py`](../../backend/app/api/x402.py) checks that capability
   for `GET /v1/public/ask/{mandate_id}/result`.

## Current and expected authorization behavior

**Current code behavior:** the capability-bound result endpoint validates the
result capability. The generic evidence endpoint does not validate that
capability or another principal scoped to an M2M mandate. Under the global
guard's current origin check, possession of the mandate ID appears sufficient
to query and return its Evidence for `origin == "M2M"`.

**Expected behavior:**

> **M2M_EVIDENCE_ACCESS_CONTROL**
>
> Evidence belonging to a capability-bound M2M purchase MUST NOT be
> retrievable by possession of mandate_id alone.
>
> Any endpoint capable of returning M2M Evidence content MUST require an
> authorization principal scoped to that mandate.

For public x402 M2M, the existing result capability is the natural
authorization, unless a separately specified mechanism is explicitly
equivalent and mandate-scoped.

## Impact assessment

- **Confidentiality:** potential disclosure of acquired Evidence content and
  its provenance to a caller who knows the mandate ID. Actual payload
  sensitivity and production access are not verified.
- **Integrity:** no write or mutation path is identified in this finding.
- **Availability:** no denial-of-service or resource-exhaustion behavior is
  established by this finding.

## Production status

`PRODUCTION_STATUS: NOT_VERIFIED`

No production endpoint was called and no production database or logs were
queried for this finding. There is no claim that production data was accessed
by a third party.

## Separate from consumer result delivery

The consumer-delivery concern is that the capability-bound result projection
omits Evidence content, even for the authorized purchaser. This finding is the
opposite authorization boundary: a different endpoint may expose Evidence
content without requiring that purchaser's capability. Fixing delivery does
not establish authorization on the generic evidence route; restricting that
route does not deliver content through the capability-bound result surface.
Track and resolve these as separate findings.

## Minimal correction options — design not selected

1. Require a mandate-scoped result capability for M2M Evidence access on this
   endpoint.
2. Deny M2M mandates on the generic evidence endpoint and direct the purchaser
   to a capability-bound result surface.

No option is selected here. A decision must preserve the existing USER and
AUTONOMOUS access behavior and define the intended public x402 content surface.

## Tests required before closure

- M2M Evidence request without capability is denied.
- Incorrect capability is denied.
- A capability for another mandate is denied.
- Correct mandate capability is authorized only if this endpoint is intended
  to serve M2M Evidence.
- USER behavior is unchanged.
- AUTONOMOUS behavior is unchanged.
- No cross-mandate Evidence disclosure is possible.

## Scope and activity

```text
CODE_FILES_MODIFIED: 0
TEST_FILES_MODIFIED: 0
MIGRATIONS_CREATED: 0
NETWORK_REQUESTS: 0
PAID_TRAFFIC: 0
DEPLOYED: false
```
