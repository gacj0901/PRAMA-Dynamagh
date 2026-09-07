# Track 3 workflow examples

These examples are prompts for real users of the public manual workflow. They
are not fixtures, synthetic activity, or a promise that every request will be
admitted. Each request is still bounded by the existing public budget, rate
limit, Redis coordination, reservation and settlement controls.

The read-only activity surface reports the effective competition profile. The
bounded production defaults are `0.50 USDC` per workflow, `20.00 USDC` per
shared daily ledger, and `0.05 USDC` per acquisition. The existing G12
reservation, settlement, idempotency, Redis coordination, rate limiting and
fail-closed checks remain authoritative. A workflow accepts at most five
ordered caller-supplied acquisition tasks; each task remains opaque to the
application and is routed through the normal Telegraph path.

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
