# PRAMA-Dynamagh invariants

- Preserve raw Telegraph responses before normalization.
- A Telegraph call always belongs to a persisted mandate.
- The EVM private key is gateway-only; never expose it through API, worker, UI, logs, or tests.
- Evidence is admitted only with valid Telegraph provenance.
- The decision gate is deterministic and versioned as `prama-gate-v0`.
- Tickets require a decision and canonical payload hashing.
- Never modify external Firecrawl, Redis, RabbitMQ, or their databases from this repository.

