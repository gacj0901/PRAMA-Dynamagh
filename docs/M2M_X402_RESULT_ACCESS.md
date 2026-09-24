# Inbound x402 M2M result access

`POST /v1/public/ask` is the inbound x402 seller rail. It remains separate
from `POST /v1/m2m/mandates`, which requires the global
`PRAMA_M2M_API_TOKEN` Bearer credential.

## Flow

1. The client sends the same intent and request to `/v1/public/ask` and
   receives a `402` challenge.
2. The client validates the payment requirements and returns a signed x402
   payment. PRAMA verifies and settles it through the configured facilitator.
3. After successful settlement, PRAMA records the inbound payment, creates a
   bounded `Mandate(origin=M2M)`, applies the existing M2M spend reservation,
   and queues its acquisition. Inbound revenue does not increase the mandate
   budget or bypass G12, reservations, or worker controls.
4. The `202` response includes `mandate_id`, `status`, `result_endpoint`,
   `status_url`, and `result_capability`. The capability is a random 32-byte
   URL-safe bearer value returned only in that response.
5. The client polls the returned URL with the capability in the
   `X-PRAMA-Result-Capability` header. The result is scoped to that one
   settled payment and mandate. It can be polled after process restarts because
   only its SHA-256 digest and mandate linkage are persisted.

Example:

```http
GET /v1/public/ask/{mandate_id}/result
X-PRAMA-Result-Capability: <result_capability>
```

The result reports persisted mandate/acquisition status and the corresponding
evidence, structural evaluation, Decision, and Ticket summaries as they become
available. Missing, incorrect, and cross-mandate capabilities all receive the
same `404 X402_RESULT_NOT_FOUND`. The capability is never accepted in a URL,
and result responses use `Cache-Control: no-store`.

The raw capability is not stored. An idempotent replay of an already-settled
request does not settle again and returns `result_capability: null`; the client
must retain the capability from the original `202` response. It may continue
using that capability after a server restart.

## Authority boundary

The result capability grants read access only to the mandate funded by the
corresponding inbound payment. It does not authenticate to `/v1/m2m/*`, create
other mandates, change the mandate's x402 context, or reveal
`PRAMA_M2M_API_TOKEN`. Inbound x402 payment and outbound Telegraph/provider
expenditure remain separate economic legs.

No E1 coverage, Decision Gate, G12/G13, Telegraph behavior, or payment
requirements are changed by this result-access mechanism.
