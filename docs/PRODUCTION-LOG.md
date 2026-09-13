# Production Log

This file is the operational record for PRAMA-Dynamagh. It contains timestamped deployment checks, runtime observations, and production evidence that should not be embedded in the timeless project README.

Each entry should record the observation time, deployed commit, component or endpoint checked, result, and any relevant run or event identifiers. Append new entries; do not rewrite historical entries.

## 2026-09-13 — Runtime verification snapshot

### Services and authority

- Public application: `https://prama-dynamagh.up.railway.app/`
- `authority_mode`: `BINDING`
- API, worker, frontend, and Gateway were online during the verification window.
- Global autonomy was enabled.
- Runtime health reported a fan-out maximum of 5 tasks per mandate and a maximum single acquisition of `0.010000 USDC`.

### Activity observed

| Scope | Observation |
| --- | --- |
| Public / M2M | 9 users, 10 workflows, 8 successful Telegraph calls, 1 multi-intent workflow, 8 evidence records, 7 decisions, 7 tickets, `0.08 USDC` settled |
| Autonomous cumulative | 1,191 workflows started, 141 successful Telegraph calls, 141 evidence records, 1,190 decisions and tickets, `1.41 USDC` settled |
| Scheduler window | 19 runs observed; no additional settled spend in that window |

### Intents and providers

The observed public activity included `CRYPTO_PRICE` and `GAS_PRICE`. The supported intent registry is broader; an intent being registered does not imply recent production demand. Observed miner identifiers included `147117`, `7320`, `8453`, and `9002`.

### G13 recovery verification

Commit `66fbe16` contained the single-observation recovery path for the `G13_CURRENT_CRITICAL_OBSERVATION_MISSING` case. Targeted tests passed (`29 passed`) and a subsequent bounded policy run entered `RUNNING`, confirming that the scheduler deadlock path was reachable after deployment.

## Entry template

```text
## YYYY-MM-DD HH:MM UTC — <short description>

COMMIT:
COMPONENTS_CHECKED:
ENDPOINTS_CHECKED:
AUTHORITY_MODE:
POLICY_STATE:
RUN_IDS:
TELEGRAPH_STATUS:
SETTLED_USDC:
EVIDENCE_DECISION_TICKET:
BLOCKER:
```
