# Bazaar intent discoverability

Production inspection on 2026-09-26 found that the configured gateway's read-only
`GET /intents` proxies Telegraph `GET /engine/v1/intents`. That registry returned
134 canonical entries with positive miner counts. The epistemic registry in
`app/epistemic/registry.py` configures evaluation targets; it is not a supported
Telegraph routing inventory. PRAMA forwards requested intents through its
existing acquisition gateway. No additional paid endpoint is introduced.

Before correction, Bazaar's body example used WEB_SEARCH and both intent aliases
were unconstrained strings. The example was not a supported-intent inventory.

The public discovery projection now derives both `intent.enum` and
`requested_intent.enum` from the configured live registry. It includes only
canonical entries with positive miner counts, excludes explicit disabled,
inactive or experimental entries, and applies the documented PRAMA incident hold
for RESEARCH_QUERY. The latter is present in the upstream registry, but registration
does not resolve the known failed routing investigation. No automatic replacement
is made. RESEARCH_SYNTHESIS is independently present in the live registry; it was
not guessed or substituted for RESEARCH_QUERY.

The observed projection contains 133 names, recorded in
[the sanitized snapshot](BAZAAR_PUBLIC_INTENTS_2026-09-26.json).
This means registry-supported routing choices, not 133 independently certified
executions, E1 coverage claims, availability guarantees or semantic task fulfillment.

There is no second hardcoded advertised list. A read-only registry lookup is
cached for at most 60 seconds; failed, malformed or incomplete responses drop the
advertised list rather than serving stale support claims. No recurring worker is
added. Refreshes happen only on discovery/challenge demand. If WEB_SEARCH is not
in the verified set, Bazaar is omitted so its retained WEB_SEARCH example cannot
contradict the schema. Payment requirements and settlement remain unchanged.
The public descriptor and MCP reuse this projection; the metrics surface reports
whether Bazaar can currently be declared. Historical indexing observation is
separate. Old catalog metadata does not refresh merely because the seller changes.

The [official Bazaar specification](https://github.com/x402-foundation/x402/blob/main/specs/extensions/bazaar.md)
allows a Draft 2020-12 JSON Schema for the HTTP request body. A string `enum` is
valid within that schema. WEB_SEARCH remains an example only. No new input
validation or restriction is imposed on the existing execution endpoint.

Tests cover parity for both aliases, WEB_SEARCH example validity, exclusion of
unsupported/experimental/disabled/held entries, registry refresh, fail-closed
discovery, unchanged payment requirements, and the single canonical paid route.
No paid test or new miner query was performed.

Validation: 93 selected tests passed (25 discovery/access tests and 68 existing
M2M, x402, consumer delivery and public-surface regressions). Nginx syntax check
passed with networking disabled. Response and client-header buffers accommodate
the larger base64 x402 declaration; the observed 133-intent header is tested
against that budget. Only API and frontend proxy require deployment.
