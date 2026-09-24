# PRAMA-Dynamagh

**Structural layer of knowledge viability for autonomous agents.**

PRAMA-Dynamagh turns an authorized mandate into a paid Telegraph acquisition, preserves the full evidence lineage, evaluates admissibility, and issues a replayable decision ticket — before an autonomous action is allowed to proceed.

![PRAMA-Dynamagh](docs/assets/prama-dynamagh-presentation.png)

Live deployment: **<https://prama-dynamagh.up.railway.app/>**

---

## 1. Why this exists

An autonomous agent can now discover a provider, pay for a signal, and act on the answer within a single execution step. Receiving an answer, however, is not the same as holding evidence for a decision.

When acquisition and decision collapse into one step, four things are lost:

- the provider, cost and provenance stop being attached to the decision they produced;
- a syntactically valid response is silently treated as sufficient for the question actually being decided;
- post-mortem reconstruction of *which* information produced *which* action becomes guesswork;
- later verification proves that an execution happened, not that the evidence justified it.

PRAMA-Dynamagh keeps these separated and persisted:

```
what was mandated → what was acquired → what counted as evidence → what was decided → what can be replayed
```

One invariant governs the system:

> **A machine decision remains bound to the evidence from which it was made.**

---

## 2. Execution pipeline

```
Mandate
  → Authority (G12 economic + G13 longitudinal)
  → AcquisitionTask
  → Private Gateway
  → Telegraph / x402
  → Miner signal
  → Evidence (raw + provenance + admissibility)
  → PRAMAgraph (admissibility classification + decision map)
  → Decision
  → Ticket (canonical hash, replay, optional anchor)
  → O_AGENT observation → longitudinal reevaluation
```

The mandate state machine is explicit and forward-only:

```
RECEIVED → PLANNED → ACQUIRING → EVALUATING → DECIDING → DECIDED → TICKETED
                                                              ↘ FAILED
```

Every transition is persisted in `mandate_transitions`. `TICKETED` and `FAILED` are terminal.

The autonomous scheduler follows a strict order and never bypasses a restrictive gate with a permissive one:

```
scheduler tick → previously authorized work? → cadence due?
              → G13 trajectory authority → G12 economic authority
              → execute the next authorized action
```

If nothing is authorized, the scheduler stays idle.

---

## 3. Components

| Component | Responsibility | Does **not** |
| --- | --- | --- |
| `frontend/` | Operator console, workflow submission, lineage and activity views | hold payment credentials; authorize actions |
| `backend/` (API) | Request validation, mandates, read models, M2M rail, persistence | sign or pay |
| `backend/` (scheduler + worker) | Select authorized due work, execute it, record every transition | override a denying gate |
| `gateway/` | Private Telegraph boundary: x402 signer, payment verification and settlement, normalized results | expose a generic transaction interface |
| `contracts/` | `PRAMATicketAnchor`, `PRAMASubnetReceiver` (Base Sepolia) | act as source of truth for a ticket |
| `docs/` | Architecture, authority, identity, autonomy, epistemic contracts | — |

Runtime topology:

```
Frontend → API → PostgreSQL
              ├→ Redis / RabbitMQ → Worker
              └→ Private Gateway → Telegraph / x402 → Base Sepolia
```

The signing key exists only inside the Gateway process. API, worker and frontend never receive it.

---

## 4. PRAMAgraph — evidence classification and the decision gate

`PRAMAgraph` (`app/pramagraph/`) is the module that turns persisted evidence into a decision. It is deliberately small: no network, no payment, no external kernel — a pure classifier plus a total decision map, both versioned and replayable.

A Telegraph result is never promoted directly into a decision. The worker persists the raw provider response as Evidence, and `PRAMAgraph.evaluation.classify` assigns its admissibility classification:

| Admissibility | Condition | Code |
| --- | --- | --- |
| `REJECTED` | acquisition did not succeed | `ACQUISITION_NOT_SUCCESSFUL` |
| `REJECTED` | no raw response persisted | `MISSING_RAW_RESPONSE` |
| `REJECTED` | empty result body | `EMPTY_RESULT` |
| `REJECTED` | provenance verification failed | `PROVENANCE_FAILED` |
| `LIMITED` | admitted with upstream warnings | `UPSTREAM_WARNING` |
| `ADMITTED` | verified, non-empty, warning-free | — |

`PRAMAgraph.fanout.structural_state` folds admissibility across every acquisition task in the mandate (including required tasks that failed outright) into one structural state, which `PRAMAgraph.evaluation.decide` maps deterministically to a decision under the frozen policy `prama-gate-v0`:

| Structural state | Decision | Reason |
| --- | --- | --- |
| `STRUCTURALLY_BLOCKED` | `BLOCK` | `REQUIRED_EVIDENCE_REJECTED` |
| `STRUCTURALLY_LIMITED` | `REVIEW` | `EVIDENCE_LIMITED` |
| `STRUCTURALLY_ADMISSIBLE` | `PERMIT` | `ALL_REQUIRED_EVIDENCE_ADMITTED` |

`PRAMAgraph.replay` recomputes evidence hashes, structural state and decision independently from persisted artifacts and reports whether they still match what was stored (§7).

This gate classifies admissibility and maps the resulting structural state to the mandate `Decision`; it makes no claim about answer meaning. `ADMITTED` means provenance-verified, non-empty and warning-free; it does not mean that evidence satisfies an E1 requirement or that an E1 target is `COMPLETE`.

---

## 5. Authority model

The current mandate path is `Evidence → PRAMAgraph → prama-gate-v0 → Decision`. E1 does not replace this mandate Decision Gate. At the pre-next-action boundary, authority checkpoints are composed explicitly and persisted as policy evaluations with canonical hashes; CD can inform authority at that boundary when an E1 evaluation exists.

| Authority | Question it answers | Vocabulary |
| --- | --- | --- |
| **CD** — epistemic (`e3-a-epistemic-decision-v0.1`) | Does the E1 snapshot support this action? | `PERMIT` / `REVIEW` / `BLOCK` |
| **G12** — economic | Is there a durable reservation, within budget, not already settled? | `PERMIT` / `DENY` |
| **G13** — longitudinal (`g13-d-structural-autonomy-v*`) | Is the *trajectory* of this agent still viable? | `CONTINUE` / `THROTTLE` / `REVIEW` / `HALT` |

Composition (`authority-composition-shadow-v0.1`) yields `ALLOW` or `RESTRICT`. Two properties matter:

- **Fail-closed applicability.** Before the first acquisition there is no E1 evaluation yet, so CD is recorded as `NOT_APPLICABLE` rather than silently permissive; G12 and G13 remain fully authoritative for that action.
- **Enforcement scope is explicit.** Composition is *binding* for `AUTONOMOUS`-origin mandates — a `RESTRICT` stops execution before any network I/O. Manual, user and M2M origins are currently observed in shadow, and the observation is persisted either way.

Each policy rule is declared with its phenomenon, inputs, predicate, output, recovery path and **falsification condition** — the rule tables are the specification, not commentary on it.

G13 recovery is deliberately narrow: a `REVIEW` caused *solely* by a missing critical observation can be released by an append-only, single-use, bounded operator authorization, itself observable by `O_AGENT`.

---

## 6. Epistemic layer (O_EPISTEMIC)

O_EPISTEMIC defines a relational evaluation framework, separate from acquisition and the mandate Decision Gate. The Intent Registry defines what PRAMA-Dynamagh can acquire. A registered intent may follow `Intent → AcquisitionTask → Telegraph / Miner → Evidence → ADMITTED → PRAMAgraph` even when it has no intent-specific E1 realization. Admission and E1 completion are distinct states.

- **E1 contracts** (`app/epistemic/contracts.py`) — canonical, float-free, timezone-explicit target and requirement bodies under `e1-canonical-v0.1`.
- **E1-C2 evaluator** (`app/epistemic/evaluator.py`) — evaluates `EpistemicTarget → Requirements → EvidenceRelations → EpistemicEvaluation`. Relations are `SATISFIES` / `CONTRADICTS` / `UNRESOLVED` / `NOT_APPLICABLE`; derived structural states are `COMPLETE` / `INCOMPLETE` / `CONTRADICTED`. `ADMITTED` evidence is an admissible input, not a claim of `COMPLETE`. Contradiction is preserved; stale evidence becomes `NOT_APPLICABLE` and leaves the requirement `UNRESOLVED`. `UNSPECIFIED_CONTRACT_CASE` is a separate, non-epistemic axis for evaluator limitation.
- **E2-B trajectory** (`app/epistemic/trajectory.py`) — append-only transitions indexed by `(trajectory_lineage_id, event_index, requirement_id)`. Lineage identity is derived ex ante from the E1/E2 semantic version tuple, so a contract change opens a new lineage instead of rewriting an old one.
- **Reference projection** (`app/epistemic/reference_projection.py`) — an offline projection of an epistemic observable, kept outside the application runtime and used only to compare exact `Fraction` sources against the float64 values an adapter actually emits.

Canonical coverage state:

- E1/E2 framework: **implemented**. The `value_feed` engine: **implemented**. `CRYPTO_PRICE`: the reference realization whose E1 target, requirements and relation contract is currently closed and validated.
- **71 registered intents ≠ 71 E1-evaluable targets.** The registry makes other intents acquirable; E1 coverage has not yet been extended to them.
- `601 CRYPTO_PRICE ≠ “PRAMA only understands crypto”.` It identifies the intent with the currently closed and validated E1 target / requirement / relation contract.
- **Current mandate authority:** `Evidence → PRAMAgraph → prama-gate-v0 → Decision`.
- **E1 authority:** `Evidence → EpistemicTarget → Requirements / Relations → E1 Evaluation → CD → authority at the boundary of the next autonomous action`. E1 evaluation is not the mandate Decision Gate.
- Claims and scores are intentionally outside the `value_feed` engine. `claim_verification` requires a separate relation engine and is not covered by `value_feed`.

Coverage roadmap:

```text
value_feed
├── CRYPTO_PRICE          VALIDATED
├── GAS_PRICE             NEXT
├── TOKEN_HOLDER_COUNT    NEXT
├── MARKET_CAP            CANDIDATE
└── TVL                   CANDIDATE

claim_verification
└── requires a separate relation engine
```

Extending E1 increases relational coverage; it does not expand semantic authority.

---

## 7. Tickets, replay and verification

A decision can be committed to a deterministic **Ticket**: a canonical payload hash over the decision core and its evidence lineage, with non-deterministic runtime metadata excluded from the commitment.

```
Persisted artifacts → deterministic replay → reconstructed lineage → ticket verification
```

Replay reads persisted artifacts only; it never issues a new paid Telegraph request. `PRAMAgraph.replay` recomputes the same commitment independently, and the same artifacts must reproduce it.

The local fixture proof that paid miner output is not authorization is documented in [`docs/PAID_OUTPUT_NOT_AUTHORIZATION.md`](docs/PAID_OUTPUT_NOT_AUTHORIZATION.md). It uses only the closed and validated `CRYPTO_PRICE` E1 target and does not alter the mandate gate or call production services.

```
GET /v1/mandates/{mandate_id}/replay      # reconstruct evaluation and decision
GET /v1/tickets/{ticket_id}/verify        # recompute the canonical commitment
GET /v1/tickets/{ticket_id}/anchor        # anchor attempt status, if any
GET /v1/tickets/{ticket_id}/share         # public, redacted projection
GET /v1/titular-check/{slug}              # hash-addressed public ticket check
```

Anchoring on Base Sepolia is an *additional* external commitment to an already-constructed ticket hash; it never substitutes for the local deterministic ticket.

| Contract | Chain | Address |
| --- | --- | --- |
| `PRAMATicketAnchor` | Base Sepolia (84532) | `0x3c1a6acfd3b7ff981c31797533169e5ee36dd6e9` |
| `PRAMASubnetReceiver` | Base Sepolia (84532) | `0x055bF3A946D780A4C043B3991c1c733f140f8124` |

ERC-8183 job creation, lifecycle tracking, callback verification and promotion of verified output into Evidence are implemented and testable. Base Sepolia anchoring is an additional configured capability. Live writes are **disabled by default** (`ERC8183_LIVE_WRITES_ENABLED=false`) and require an explicit opt-in after read-only preflight.

---

## 8. Safety and accounting invariants

- Payment state is reconciled before any ambiguous retry; a settled payment cannot be charged twice for the same acquisition.
- Spend authorization is a durable PostgreSQL reservation with explicit settlement, coordinated with Redis pre-spend and rate limiting. Caps apply server-side and cannot be bypassed from the frontend.
- One shared cap governs manual, public, M2M and autonomous execution.
- External provider failures stay observable and attributable; they do not silently rewrite G13 history.
- Recovery authorizations are append-only, single-use, bounded and observable.
- Authority, payment, idempotency and concurrency guards are all evaluated *before* external execution.
- Signer material never leaves the Gateway; the M2M rail exposes no signer, no arbitrary calldata, no payment destinations, no anchoring or ERC-8183 controls, and no autonomy policy mutation.

Reference limits (see `.env.example` for the authoritative list):

| Setting | Default |
| --- | --- |
| `PUBLIC_MAX_MANDATE_USDC` | `0.050000` |
| `M2M_MAX_WORKFLOW_USDC` | `0.010000` |
| `TELEGRAPH_MAX_PAYMENT_USDC` | `0.010000` |
| `PUBLIC_DAILY_SPEND_CAP_USDC` / `GLOBAL_DAILY_SPEND_CAP_USDC` | `1.00` |
| `PUBLIC_MANDATE_RATE_LIMIT` / window | `5` per `3600s` |
| `FANOUT_MAX_TASKS_PER_MANDATE` | `5` |
| `AUTONOMY_GLOBAL_ENABLED` | `false` |
| `ERC8183_LIVE_WRITES_ENABLED` | `false` |

---

## 9. Identity and observation

`AgentIdentity` names the acting autonomous principal and is propagated through the whole lineage:

```
AgentIdentity → Mandate → AutonomyRun / M2M execution → UsageEvent → Decision → Ticket
```

Identity resolution is scoped and fail-closed, which keeps autonomous and M2M histories from collapsing into one unattributed stream.

`O_AGENT` (`o-agent-v0`) is a read-only deterministic projection of persisted artifacts for a single identity: execution order, origin, acquisition occurrence, local decision outcome, cost, latency where available, attempts, failure and recovery, recurrence, budget exposure, evidence and ticket completion. Missing telemetry stays explicitly missing — it is never imputed.

A second observer, `O_EVIDENCE_PROVENANCE v0.1` (`app/observers/provenance.py`), runs in shadow after each mandate completes. It records the binary discontinuity of the frozen `Mandate → AcquisitionTask → TelegraphCall → Evidence` chain as a dimensionless stream with a strictly causal expectation, and exposes its state at `GET /v1/observer/provenance/status`. It is downstream of the evidence lineage and upstream of no decision path.

Both observers observe; they do not decide. The separation is the point:

> A sequence of locally valid decisions does not imply a viable autonomous trajectory.

---

## 10. API surface

```
POST /v1/mandates                              create a bounded manual workflow
GET  /v1/mandates                              operator inventory
GET  /v1/mandates/{id}                         mandate state
GET  /v1/mandates/{id}/timeline                persisted transitions
GET  /v1/mandates/{id}/acquisitions            tasks, provider, cost, latency
GET  /v1/mandates/{id}/evidence                raw + provenance + admissibility
GET  /v1/mandates/{id}/evaluation              structural evaluation
GET  /v1/mandates/{id}/decision                decision and reason codes
GET  /v1/mandates/{id}/replay                  deterministic reconstruction
GET  /v1/mandates/{id}/ticket                  ticket and lineage

POST /v1/m2m/mandates                          authenticated machine rail (Bearer)
GET  /v1/m2m/mandates/{id}
GET  /v1/m2m/tickets/{id}

GET  /v1/autonomy/status | /policies | /runs   bounded autonomous execution
GET  /v1/agents/{agent_id} | /disclosure       identity and disclosure
GET  /v1/observer/...                          O_AGENT read models
GET  /v1/public/activity                       public activity projection
GET  /health                                   effective caps and authority mode
```

Minimal workflow:

```bash
curl -X POST http://localhost:8000/v1/mandates \
  -H 'content-type: application/json' \
  -d '{
    "actor_id": "operator-1",
    "text": "current BTC price in USD",
    "max_budget_usdc": "0.010000",
    "acquisitions": [{"query": "current BTC price in USD"}]
  }'
```

Then follow `/timeline`, `/evidence`, `/decision`, `/ticket`, and verify with `/v1/tickets/{ticket_id}/verify`.

---

## 11. Local development

Requirements: Docker Compose, Python 3.11+, Node.js 20+, and the variables described in `.env.example`. Production credentials are never committed; `.env.example` carries names and safe examples only.

```bash
cp .env.example .env
docker compose up --build
```

Services: `postgres`, `api`, `worker`, `gateway`, `frontend`. Redis and RabbitMQ are reached over an external Docker network (`EXTERNAL_SERVICES_NETWORK`) and are never modified by this repository.

Tests:

```bash
cd backend   && python -m pytest -q     # PostgreSQL-backed unit and integration suite
cd gateway   && npm test                # Telegraph, x402, chain and callback-verifier units
cd contracts && npm test                # Hardhat: anchor and subnet receiver
cd frontend  && npm test                # unit; npx playwright test for browser checks
```

The integration suite requires a live PostgreSQL instance; `scripts/validate_authority_postgres.ps1` is the reference harness used for authority validation.

---

## 12. Current state and limitations

Stated plainly, because the value of the system is that it does not overclaim.

**Implemented and validated:** Telegraph/x402 acquisition through the private Gateway, evidence persistence with provenance, PRAMAgraph evaluation and decision, deterministic tickets, deterministic replay, authenticated M2M execution, bounded autonomous execution, `AgentIdentity`, `O_AGENT v0`, persisted E1 epistemic evaluations, and binding authority composition for autonomous origin. The separate Telegraph MCP access plane is implemented and validated through contract, protocol, and dark-preflight tests; production traffic currently uses Gateway.

**Deliberately not yet claimed:**

- The mandate `Decision` is produced by PRAMAgraph's `prama-gate-v0`, a deterministic admissibility map over persisted artifacts. The epistemic layer informs the autonomous action boundary, not that decision.
- Authority composition is binding for autonomous execution; other origins are observed in shadow.
- Only the `CRYPTO_PRICE` E1 realization is currently closed and validated. Other registered intents remain acquirable without an E1-evaluable target. Claims and scores remain outside this engine; confidence/score-based intents would require a `ScoreThresholdEngine` that is intentionally undesigned.
- Longitudinal *intervention* (acting on trajectory rather than observing it) is specified in the G13 policy vocabulary but the surrounding governance loop remains partial.
- `docs/ARCHITECTURE.md` still describes the Phase 0 topology and lags the current authority and epistemic layers.

Operational observations, deployment checks and runtime evidence are appended — never rewritten — in [`docs/PRODUCTION-LOG.md`](docs/PRODUCTION-LOG.md).

---

## 13. Documentation

| Document | Contents |
| --- | --- |
| [`AGENTS.md`](AGENTS.md) | Non-negotiable repository invariants |
| [`docs/FULL_AUTONOMY.md`](docs/FULL_AUTONOMY.md) | Bounded autonomous execution policy |
| [`docs/G13_O_AGENT.md`](docs/G13_O_AGENT.md) | Observation contract |
| [`docs/G13_AGENT_IDENTITY.md`](docs/G13_AGENT_IDENTITY.md) | Identity propagation and scoping |
| [`docs/O_EPISTEMIC_E2B.md`](docs/O_EPISTEMIC_E2B.md) | Trajectory contract and lineage rules |
| [`docs/O_EPISTEMIC_PRAMA_PARTIAL_CORRESPONDENCE_V0_1.md`](docs/O_EPISTEMIC_PRAMA_PARTIAL_CORRESPONDENCE_V0_1.md) | What does and does not correspond to PRAMA today |
| [`docs/authority-runtime-shadow.md`](docs/authority-runtime-shadow.md) | Shadow checkpoint semantics |
| [`docs/PAID_OUTPUT_NOT_AUTHORIZATION.md`](docs/PAID_OUTPUT_NOT_AUTHORIZATION.md) | Persisted fixture proof and replay invariants |
| [`docs/TITULAR_CHECK.md`](docs/TITULAR_CHECK.md) | Public hash-addressed ticket check |
| [`docs/competition-workflows.md`](docs/competition-workflows.md) | Multi-intent fan-out workflows |
| [`docs/PRODUCTION-LOG.md`](docs/PRODUCTION-LOG.md) | Append-only operational record |

---

## 14. License

No license file is currently present in this repository; all rights are reserved by default. Add a `LICENSE` file before external reuse.
