# Track 3 workflow examples

These examples are prompts for real users of the public manual workflow. They
are not fixtures, synthetic activity, or a promise that every request will be
admitted. Each request is still bounded by the existing public budget, rate
limit, Redis coordination, reservation and settlement controls.

The read-only activity surface reports the effective competition profile. The
bounded target settings are `0.05 USDC` per public workflow, `1.00 USDC` per
shared daily ledger, and `0.01 USDC` per acquisition. M2M and autonomous
workflows retain a separate hard ceiling of `0.01 USDC`. The existing G12
reservation, settlement, idempotency, Redis coordination, rate limiting and
fail-closed checks remain authoritative. A workflow accepts at most five
ordered caller-supplied acquisition tasks; each task remains opaque to the
application and is routed through the normal Telegraph path.

`FANOUT_MAX_TASKS_PER_MANDATE` explicitly bounds task count (default/hard maximum
5; values above the ceiling are clamped). Public creation above the effective
count returns 422. `PUBLIC_MANDATE_RATE_LIMIT=5` applies per 3600 seconds.
Only production runtime receipts establish activation of these settings.

Fan-out is sequential within a mandate. A failed task remains explicit and
does not prevent later tasks with available budget from executing. Unknown
payment outcomes are not retried and keep the outstanding reservation held;
they are not represented as zero cost. Known unused budget is released when
all payment outcomes are established. The atomic reserve/settle/release
implementation is unchanged.

The versioned generic fan-out evaluator records required acquisition failure
as a limitation; it does not impute evidence. `prama.ticket.fanout.v0.1`
commits task identities, query hashes, statuses and failures. Old v0 tickets
retain their original construction and replay semantics.

Authority checkpoints run in separate transactions with no enforcement.
Existing Decisions and G12 reservation states are observed; E3 is evaluated
only where an actual persisted E1 evaluation exists. G13 is evaluated for an
actual autonomous run. Missing input/checkpoint failure is explicit; if the
database is unavailable even the diagnostic row cannot be persisted and a
sanitized error is logged. No non-CRYPTO_PRICE typed E1 coverage is claimed.

1. **Crypto price** — “What is the current price of Bitcoin in USD?”
2. **Source comparison** — “Compare the current USD price of Bitcoin from the available intelligence sources.”
3. **Protocol lookup** — “What is the current status and official documentation URL for the requested protocol?”
4. **Market snapshot** — “Provide a current, source-attributed market snapshot for the requested asset.”

The public API accepts an optional ordered list of acquisition tasks. Each task
carries a caller-supplied query and optional opaque intent label; the
Gateway/Telegraph path remains responsible for the actual Miner and returned
intent. Tasks execute sequentially under one durable workflow reservation, and
the final Decision/Ticket is emitted only after all required tasks finish.

## Public activity scope

The public activity surface aggregates persisted `MANUAL` and external `M2M`
workflows. `AUTONOMOUS`, internal, and observer/shadow records are excluded.
The database does not carry a separate historical TEST/SHADOW environment tag
for every row, so the endpoint reports that limitation instead of guessing.

## Shareable result

Completed Tickets expose a bounded `/v1/tickets/{ticket_id}/share` summary. It
contains workflow type, acquisition status, intent/miner labels, evidence and
decision statuses, hashes, limitations, and verifier/replay links. It does not
include mandate text or provider raw payloads.
