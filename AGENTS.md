# PRAMA-Dynamagh invariants

- Preserve raw Telegraph responses before normalization.
- A Telegraph call always belongs to a persisted mandate.
- The EVM private key is gateway-only; never expose it through API, worker, UI, logs, or tests.
- Evidence is admitted only with valid Telegraph provenance.
- The decision gate is deterministic and versioned as `prama-gate-v0`.
- Tickets require a decision and canonical payload hashing.
- Never modify external Firecrawl, Redis, RabbitMQ, or their databases from this repository.
- New epistemic intents are added to `app/epistemic/registry.py` as configuration
  entries, never as new modules, unless they do not fit any existing engine —
  in that case, discuss the new engine before writing code.
- TODO (future): confidence/score-based intents (Group C in the Telegraph
  taxonomy) require a `ScoreThresholdEngine`; do not design it yet.
- TODO (wiring): epistemic evaluation is not yet hooked into the mandate
  pipeline; targets are only constructed in tests today.

