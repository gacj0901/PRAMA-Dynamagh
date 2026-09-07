# Track 3 workflow examples

These examples are prompts for real users of the public manual workflow. They
are not fixtures, synthetic activity, or a promise that every request will be
admitted. Each request is still bounded by the existing public budget, rate
limit, Redis coordination, reservation and settlement controls.

1. **Crypto price** — “What is the current price of Bitcoin in USD?”
2. **Source comparison** — “Compare the current USD price of Bitcoin from the available intelligence sources.”
3. **Protocol lookup** — “What is the current status and official documentation URL for the requested protocol?”
4. **Market snapshot** — “Provide a current, source-attributed market snapshot for the requested asset.”

The current public API creates one acquisition task per manual mandate. A
multi-intent workflow is not advertised until the Gateway contract and worker
coordination can express it without increasing the workflow budget or creating
duplicate paid attempts.

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
