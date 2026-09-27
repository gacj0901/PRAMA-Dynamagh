# Bazaar intent discoverability — superseded interpretation

The 2026-09-26 change `61ab1d4fc456695f13a4004dbb2ebb9f9e1ba7f3`
projected a Telegraph registry into both Bazaar request-field enums. That was
valid JSON Schema but the wrong application boundary: `requested_intent` is an
optional application-level semantic hint, not necessarily a Telegraph Intent_ID.
Registry membership and miner counts did not establish PRAMA request support.

The capability-discovery correction removes that registry projection and its
133-name snapshot from active discovery. History remains available in Git.
There is no local Telegraph routing registry, provider lookup during discovery,
or guessed enum. The single paid resource remains `POST /v1/public/ask`.
WEB_SEARCH remains an example, not an exhaustive capability list.

See [the alignment evidence](CAPABILITY_DISCOVERY_V2_ALIGNMENT.md) and the
[PRAMA-owned capability descriptor](https://prama-dynamagh.up.railway.app/v1/public/capabilities).
Telegraph owns protocol resolution, eligibility/ranking and Miner selection;
PRAMA owns request metadata, server constraints, Evidence, evaluation, authority,
Decision, Ticket and Consumer Result delivery. Settlement and kernel semantics
are unchanged. No paid traffic was generated for this correction.
