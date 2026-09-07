# PRAMA-Dynamagh

**Deterministic replay infrastructure for paid machine intelligence.**

```text
Mandate
   ↓
Acquisition (Telegraph / x402)
   ↓
Evidence
   ↓
Epistemic Evaluation
   ↓
Decision
   ↓
Verifiable Ticket  →  (optional on-chain anchor)
```

Agents can already pay for intelligence. What they cannot do is prove, later, which evidence produced which decision. PRAMA-Dynamagh closes that gap: every decision remains bound to its evidence lineage and can be re-verified for free — no new paid call, no trust in the operator.

**Live:** https://prama-dynamagh.up.railway.app/

---

## The one-sentence version

> **Every machine decision stays bound to the exact evidence that produced it — and anyone can replay it.**

---

## What the system does (implemented, running)

- **Preserves paid acquisitions raw.** Telegraph/x402 responses are stored byte-identical before any normalization. Provider, cost, latency, and signal hash are never detached from the payload.
- **Admits evidence deterministically.** The same artifact under the same admission version always gets the same admission state. Insufficient evidence yields `UNRESOLVED` — never a silent pass, never an imputed zero.
- **Evaluates epistemically, not semantically.** Each admitted evidence item is bound to each explicit requirement via an auditable `relation_basis` (`SATISFIES` / `CONTRADICTS` / `UNRESOLVED` / `NOT_APPLICABLE`). Contradictions are preserved, never averaged away.
- **Issues deterministic Decision Tickets.** Canonical hashing over the decision core and its evidence lineage. The same persisted artifacts reproduce the same Ticket commitment.
- **Replays for free.** Verification runs against persisted artifacts. No provider re-payment, no external calls.
- **Bounds itself.** Per-mandate and daily spend caps, atomic PostgreSQL reservations, Redis pre-spend coordination, rate limits, idempotency — enforced server-side, fail-closed. The frontend cannot bypass any of it.

---

## Trust boundaries (enforced in code)

```text
Public client / Agent
        ↓
       API          ← no signing key
        ↓
      Worker        ← no signing key
        ↓
  Private Gateway   ← the ONLY component holding the EVM key
        ↓
Telegraph / Base Sepolia
```

- The EVM key exists only inside the Gateway. It never enters API handlers, workers, UI, logs, or tests.
- The Gateway exposes no generic transaction or deployment interface.
- Destructive surfaces (ERC-8183 writes, ticket anchoring, cancellation) deliberately return 404 in the public deployment.

---

## Intent surface

The pipeline is **intent-agnostic**: Telegraph is one pluggable evidence provider, and any of the 40 Telegraph intents — Tier A deterministic (`CRYPTO_PRICE`, `STOCK_PRICE`, `ONCHAIN_TX_LOOKUP`, `SSL_VERIFICATION`, …) or Tier B LLM-judged (`RESEARCH_QUERY`, `SENTIMENT_ANALYSIS`, `FACT_CHECK`, …) — feeds the same Mandate→Evidence→Evaluation→Decision→Ticket chain.

Typed epistemic contracts are added per target type. E1 v0.1 ships with `CRYPTO_PRICE`; new target types are new contracts, not rewrites.

---

## Verified capabilities

| Capability | Status |
|---|---|
| Telegraph acquisition + x402 payment | ✅ Production |
| Raw-response preservation & provenance | ✅ |
| Deterministic evidence admission gate | ✅ |
| O_EPISTEMIC E1 relational evaluation | ✅ |
| Deterministic Decision Ticket + free replay | ✅ |
| Bounded autonomous execution (budget/cadence caps) | ✅ Production |
| Authenticated M2M rail | ✅ Production |
| Persistent AgentIdentity + O_AGENT v0 observation | ✅ |
| Policy evaluation (CD/G12/CDG), shadow mode | ✅ Persisted, observing only |
| ERC-8183 execution + verified callback | ✅ Demonstrated (write surface disabled in public prod) |
| Base Sepolia Ticket anchoring | ✅ Demonstrated (optional, off by default) |
| Policy enforcement (active PERMIT/REVIEW/BLOCK) | Not yet enabled |

Nothing marked "demonstrated" is mocked. "Disabled in public prod" means the write endpoint deliberately returns 404.

---

## Demo: prove the replay

What follows is the exact sequence a jury or auditor can run to verify the core claim. All read endpoints are public. The paid step (mandate creation) is capped at 0.01 USDC and executed server-side.

### 0. Health check

```bash
curl https://prama-dynamagh.up.railway.app/health
```

Expected: `status: ok`, plus the live public execution caps (`max_mandate_usdc`, `daily_spend_cap_usdc`, rate limits). This proves the bounds are server-side configuration, not UI.

### 1. Create a bounded mandate (paid, capped)

```bash
curl -X POST https://prama-dynamagh.up.railway.app/v1/mandates \
  -H "Content-Type: application/json" \
  -d '{
    "text": "What is the current price of BTC in USD?",
    "acquisitions": [
      {"query": "BTC/USD spot price", "intent": "CRYPTO_PRICE", "required": true}
    ],
    "max_budget_usdc": "0.01"
  }'
```

→ returns `mandate_id`. Within the budget cap, the worker executes: Telegraph call → raw response persisted → evidence admission → E1 epistemic evaluation → decision → ticket.

### 2. Inspect the lineage

```bash
curl https://prama-dynamagh.up.railway.app/v1/mandates/{mandate_id}
```

Expected: full chain — acquisition task, Telegraph call (with signal hash, miner, cost, latency), evidence with admission state, epistemic evaluation with per-requirement relations and explicit `relation_basis`, decision, ticket.

Look specifically for: any `UNRESOLVED` left explicit, and the `relation_basis` field on each evidence relation (e.g. `rule: exact_field_match, evidence_field: asset, expected_value: BTC, observed_value: BTC`).

### 3. Verify the ticket — free replay, no re-payment

```bash
curl https://prama-dynamagh.up.railway.app/v1/tickets/{ticket_id}/verify
```

Expected: `VALID` with the ticket hash recomputed from persisted artifacts. **This is the proof**: the decision reconstructs from stored evidence, byte for byte, without paying Telegraph again.

### 4. (Optional) Show the system bounding itself

The health endpoint and mandate history demonstrate live instances of: daily spend cap enforcement, explicit `UNRESOLVED` states where evidence was insufficient, and shadow policy evaluations (CD/G12/CDG) persisted for each autonomous run — the system observing its own trajectory and cost before acting.

---

## Stack

FastAPI · Celery worker · isolated Gateway (TypeScript/ethers) · PostgreSQL (JSONB lineage) · Redis · RabbitMQ · minimal Vite/React frontend · Solidity anchors on Base Sepolia. Deployed as isolated services on Railway.

---

## Non-goals (explicit)

PRAMA-Dynamagh does **not**: judge truth, predict outcomes, score providers, or replace Telegraph's scorer. It is the layer that makes everyone else's claims *checkable*. New epistemic target types, active policy enforcement, and on-chain anchoring are extensions of the same pipeline — the pipeline itself does not change.

---

## Versioning discipline

Every artifact in the chain — admission contract, observer, evaluator, policy, ticket schema — carries an explicit version string and a canonical hash. Replay validity is defined per version tuple, never against "the latest".
