# Paid miner output is not authorization to act

## Claim

**Paid miner output is not authorization to act.** A successful settlement and
Miner response establish that an acquisition was fulfilled. The persisted
Evidence conditions still determine admissibility and the mandate Decision.

## Service

`POST /v1/public/ask` may acquire intents registered by the service. Registry
membership describes acquisition capability; it does not confer E1 coverage or
authorize a downstream action.

## Current mandate Decision

```text
Evidence
→ PRAMAgraph
→ prama-gate-v0
→ Decision
```

The test below calls the existing classifier, structural evaluator, and
`prama-gate-v0` decision map. It does not change the mandate gate, G12, or G13.
E1 evaluation remains a separate relation evaluation; it does not replace the
current mandate Decision Gate.

## E1 coverage

The E1 target / requirement / relation contract is currently closed and
validated for `CRYPTO_PRICE` only.

```text
71 registered intents
≠
71 E1-evaluable targets
```

Extending E1 increases relational coverage; it does not expand semantic authority.

## Reproducible fixture proof

Run from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/unit/test_paid_output_not_authorization.py `
  tests/unit/test_x402_public.py::test_x402_manifest_is_public_json_and_points_to_post_seller `
  tests/unit/test_o_epistemic_c2_evaluator.py -q -p no:cacheprovider
```

The proof input is [`tests/fixtures/paid_output_not_authorization.json`](../backend/tests/fixtures/paid_output_not_authorization.json).
Both records contain the same exact `CRYPTO_PRICE` request and a fixture-only
`SETTLED` payment receipt for `0.010000 USDC`. The test persists the Miner call,
Evidence, target, requirements, typed evidence, E1 relations/evaluation,
structural evaluation, Decision, and Ticket to an in-memory SQLite database.
No payment facilitator or acquisition adapter is used. Replay reads those
persisted rows; socket connection attempts are blocked and fail the test.

### CASE A — PERMIT

```text
payment: SETTLED (fixture only)
request: CRYPTO_PRICE / What is the current price of BTC in USD?
evidence_id: a4111111-1111-4111-8111-111111111111
evaluation: E1 COMPLETE; all required relations SATISFIES
decision: PERMIT / prama-gate-v0 / ALL_REQUIRED_EVIDENCE_ADMITTED
ticket_id: aa111111-1111-4111-8111-111111111111
replay_result: E1 hash match; mandate replay matches; Ticket VALID
```

### CASE B — REVIEW

```text
payment: SETTLED (fixture only)
request: CRYPTO_PRICE / What is the current price of BTC in USD?
evidence_id: b4111111-1111-4111-8111-111111111111
evaluation: E1 CONTRADICTED; asset_identity relation CONTRADICTS
decision: REVIEW / prama-gate-v0 / EVIDENCE_LIMITED
ticket_id: bb111111-1111-4111-8111-111111111111
replay_result: E1 hash match; mandate replay matches; Ticket VALID
```

Case B keeps payment, request, intent, and call success unchanged. Its fixture
Evidence carries an upstream warning and reports `ETH` against the precommitted
`BTC` target. The warning makes Evidence `LIMITED`, which the existing mandate
gate maps to `REVIEW`; E1 independently preserves the identity contradiction.
Neither payment success nor the E1 result is substituted for the mandate gate.

### Checked invariants

| Invariant | Result |
| --- | --- |
| Same request and intent | Yes |
| Payment settled in both cases | Yes, fixture-only |
| Different Evidence condition | Yes: `ADMITTED`/matching vs `LIMITED`/contradicting |
| Different mandate authorization | Yes: `PERMIT` vs `REVIEW` |
| New payment on replay | No; persisted settled receipt count is unchanged |
| Network on replay | No; socket connection attempts are blocked |
| E1 target | `CRYPTO_PRICE` only |
| `prama-gate-v0`, G12, G13 changed | No |

The fixture proves deterministic behavior of the local persisted-artifact path;
it is not evidence of a live settlement or production adoption event.

## Public capability description

The true402 seller manifest keeps its x402 1.0 fields and existing string-list
`capabilities` field. The capability entries and existing `description` state
the principle and current E1 coverage; no manifest keys were added. The
true402 example manifest uses this same string-list form for capabilities.
