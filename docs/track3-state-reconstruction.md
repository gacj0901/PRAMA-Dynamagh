# Track 3 — baseline, 2026-09-07

Source: origin/main 93122c265367eb31eadc6d4d2da131c96a6952f9. Isolated branch codex/track3-operational-closure. Existing main worktree authority-shadow edits remain untouched.

Baseline: 159 unit tests and 48 PostgreSQL integration tests passed on a new isolated local PostgreSQL 16 database, migrated to 0019. No production tests or paid calls were used for this baseline.

| Feature | Implemented | Committed | Pushed | Deployed | Active | Blocker |
| --- | --- | --- | --- | --- | --- | --- |
| Explicit public/M2M acquisition list | YES, initial sequencing | 93122c2 | YES | API YES; worker stale | NOT_VERIFIED | No multi-task production trace; worker old |
| Partial failure continuation | NO | NO | NO | NO | NO | One failure terminates whole mandate |
| Incremental settlement | YES, source | 93122c2 | YES | Worker stale | NOT_VERIFIED | Source/process drift |
| CD/CDG shadow persistence | Local unfinished work only | NO | NO | NO | NO | Runtime module absent; production policy_evaluations empty |
| G12 economic gate | YES | YES | YES | YES | Reservations and spending observed | Effective limits differ by service |
| Frontend API proxy | YES | YES | YES | YES | HTTP 200 API and proxy health | None observed |

## Mandatory cap inventory before edits

| Limit | Source / effective value |
| --- | --- |
| Per acquisition | Source public_safety.MAX_SINGLE_ACQUISITION_USDC = 0.05; gateway/server.ts maxPayment hard clamps to 0.01; Railway Gateway TELEGRAPH_MAX_PAYMENT_USDC=0.01 |
| Workflow | Source MAX_WORKFLOW_SPEND_USDC/M2M_MAX_WORKFLOW_USDC=0.50; API runtime public=0.01, M2M=0.50; worker runtime public=0.01, M2M=0.01 |
| Global daily | API and worker runtime 0.50; source fallback/max raised to 20.00 in 93122c2 |
| Rate | API and worker runtime 3 per 3600 seconds, public_safety.public_rate_limit; keyed by transport peer |
| Concurrency | No CLI concurrency flag found in /proc; cpu_count=48. Exact pool concurrency NOT_VERIFIED at this snapshot |
| Fan-out | Source competition_max_calls_per_workflow and Pydantic lists bound to 5; no FANOUT_MAX_TASKS_PER_MANDATE env contract yet. At maximum 0.01 per task the effective public budget funds one task; cheaper actual calls could permit more, so 1 is a fully-funded count, not an invariant on count |

## Explicit findings; no silent semantic repair

1. **RAW_UPSTREAM_NOT_PERSISTED_INTACT**: Gateway normalizes the original Telegraph JSON before returning it. Backend raw_response persists that Gateway response before Evidence normalization, not the intact upstream response. Invalid Gateway/Telegraph responses can fail before a TelegraphCall row exists. The broad raw-preservation invariant is not established. This closure retains existing normalization semantics and reports the finding.
2. **TYPED_E1_NOT_IN_PAID_RUNTIME**: Paid worker decisions consume StructuralEvaluation, not EpistemicEvaluation. Production epistemic_evaluations is empty; worker lacks the E1 module. CRYPTO_PRICE E1 exists in source but must not be claimed active from transport intent. Generic structural evaluation has empty contradiction_codes and is not a relational contradiction detector.
3. **API_WORKER_DRIFT**: API deployed commit is 93122c2. Worker and Gateway deployments do not expose a commitHash in Railway metadata; their exact source HEADs are NOT_VERIFIED. Runtime fingerprints show worker differs from API. In particular M2M cap differs 0.50 vs 0.01.
4. **BASELINE_SHADOW_ABSENT**: policy_evaluations has zero rows; no CD/CDG shadow runtime module in either API or worker.
5. **UNCERTAIN_SPEND_HELD**: Production ledger for 2026-09-07 has 0.020000 spent and 0.010000 reserved, including one autonomous unresolved reservation. It is not released or rewritten by this task. Unknown payment outcomes must never be treated as zero or retried for payment.

Other inspected invariants: persisted mandate before Gateway; deterministic versioned admission/Decision; separate verification, classification and Decision; canonical ticket/replay without paid requests; observers do not enforce; signer environment key present in Gateway only and absent in API/worker/frontend. This does not certify all historical logs or every external call.

Requested correction is explicit: restore the 0.01 M2M/autonomous and per-acquisition ceilings, configure public mandate 0.05 and daily 1.00, retain Gateway 0.01 and existing atomic reserve/settle/release bodies. Existing source already supports settle_spend(finalize=False).

Detailed sanitized baseline receipts reside in the task's track3 evidence folder. SSH access was explicitly authorized temporarily and must be removed at completion.
