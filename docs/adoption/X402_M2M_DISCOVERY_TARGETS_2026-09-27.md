# x402 / M2M discovery targets — 2026-09-27

Research was read-only. No accounts, signatures, payments, or external
registrations were made. A submission is not a listing, and a listing is not
evidence of M2M demand.

## Current platform findings

| Platform | Official surface / purpose | Active | Submission and network fit | Result |
|---|---|---:|---|---|
| PayAI Bazaar | [Bazaar discovery API](https://docs.payai.network/x402/facilitators/bazaar); facilitator-backed resource index | YES | Resource declares Bazaar metadata; cataloging behavior is facilitator-specific and can require settlement. Base Sepolia supported in the existing seller declaration. | VERIFIED exact `/v1/public/ask` resource from dated lookup; latest metadata propagation PENDING. No payment to refresh. |
| Agent402 | [Agent402 marketplace](https://marketplace.agent402.app/marketplace); x402 service marketplace | INDETERMINATE | Search results describe seller registration and signup, but direct official page fetch returned HTTP 410. Current unauthenticated registration and testnet support are not established. | PENDING verification; manual account action would be required if the official seller page is restored. |
| x402-list | [Directory](https://www.x402-list.com/) and [official API/submission docs](https://www.x402-list.com/api) | YES | POST `/api/v1/submit` accepts service details and probes HTTP 402. Docs state free-compute hosting incurs a non-refundable $1 USDC Base payment; Railway classification and Base Sepolia acceptance are not explicit. | PENDING; not submitted because the host may incur a fee and the request prohibits payment. Exact payload is in `submissions/x402-list.md`. |
| true402 | [Docs](https://true402.dev/docs), catalog, manifest and marketplace | YES | Live docs state there is no testnet on this deployment; Base is `eip155:8453` mainnet, x402 v2. The manifest is a catalog, not proof of testnet compatibility. | INCOMPATIBLE_CURRENTLY. Do not adapt PRAMA's payment contract. |
| x402.new | [Directory](https://x402.new/) and [provider instructions](https://x402.new/submit) | YES | Crawler/Bazaar-derived; instructions say no direct form, continuous indexing. Coinbase facilitator's `discoverable: true` is described; PRAMA uses PayAI. No alternative direct submission confirmed. | PENDING_INDEX_PROPAGATION; no exact-resource result confirmed in this read-only research. Recheck after metadata propagation. |
| AgentIndex / x402looker | [AgentIndex](https://www.agentindex.ai/); general cross-protocol agent directory. A separate AgentIndex x402 API was found, but current official seller registration and testnet support were not verified. | YES for AgentIndex; x402looker INDETERMINATE | AgentIndex says brands can claim listings; auth flow and testnet support not documented in the verified official source. | MANUAL_ACTION_REQUIRED before listing; no submission. x402looker not independently confirmed as a current directory. |
| x402.direct | [Directory API docs](https://x402.direct/docs); searchable x402 index | YES | Free GET catalog and paid search; its docs explicitly describe search/payment on Base mainnet. No seller submission mechanism was found. | INCOMPATIBLE_CURRENTLY for Base Sepolia; do not advertise as listed. |
| Run402 | [Run402 docs](https://docs.run402.com/) and [product overview](https://run402.com/humans); agent app infrastructure, not a general service directory | YES | Not a third-party x402 discovery/listing channel. | REJECTED as unrelated to this campaign; no integration or listing claim. |
| x402scan (additional) | [Merit Systems catalog](https://www.merit.systems/developers), [discovery/registration spec](https://github.com/Merit-Systems/x402scan/blob/main/docs/DISCOVERY.md), [OpenAPI](https://www.x402scan.com/openapi.json) | YES | Public resource registry; its OpenAPI says register/register-origin writes require SIWX wallet authentication. Read/search endpoints are paid. The current official spec does not establish Base Sepolia indexing. | MANUAL_ACTION_REQUIRED; do not bypass wallet authentication or spend on paid reads. High relevance, Tier 1 after an authorized operator registration. |
| EXVIV (additional) | [x402 market directory](https://exviv.com/x402); machine-readable open feed plus paid aggregated query | YES | Public businesses feed; filtered query costs $0.05 USDC on Base. No seller registration path found. | WATCH / consumer-side index only; no query payment or listing claim. |

## Tiers

### TIER_1

- PayAI Bazaar: already indexed and the only confirmed exact resource listing.
- x402-list: current machine directory with endpoint probe and human review; not
  submitted because the fee may apply and payment is disallowed.
- x402scan: current x402 registry with documented discovery and registration;
  SIWX authentication blocks safe unauthenticated submission.
- Agent402: relevant marketplace but current official seller flow could not be
  verified; hold pending a live official registration surface.
- x402.new: meaningful crawler-derived directory; verify actual PayAI-to-index
  propagation before upgrading from pending.

### TIER_2

- x402.direct: relevant index, but current documented searchable/payment surface
  is Base mainnet and no seller submission mechanism was found.
- AgentIndex: broad agent directory, not confirmed as an x402-specific index;
  manual claim flow and testnet acceptance need operator review.

### WATCH

- EXVIV: useful read/search index with open provider data; its query path is paid
  and no provider-submission mechanism was identified.
- x402looker: not independently verified as a distinct current platform.

### REJECTED

- Run402 for this campaign: active product, but an infrastructure provisioning
  platform rather than a third-party x402 discovery directory.

## Additional machine discovery surface

x402scan is included because its current official materials document an x402
resource registry, a public API/MCP, discovery precedence, and registration.
Registration itself requires SIWX, so this work did not sign a wallet request.
EXVIV is retained as a watch item because it has a public business feed, but its
paid query is neither necessary nor authorized for this listing campaign.

## Sources checked

- x402 Foundation [Bazaar extension](https://github.com/x402-foundation/x402/blob/main/docs/extensions/bazaar.mdx)
- PayAI [Bazaar docs](https://docs.payai.network/x402/facilitators/bazaar)
- [x402-list submission/API](https://www.x402-list.com/api) and [methodology](https://www.x402-list.com/methodology)
- [true402 protocol docs](https://true402.dev/docs)
- [x402.new submit guidance](https://x402.new/submit)
- [Agent402 marketplace](https://marketplace.agent402.app/marketplace)
- [AgentIndex official site](https://www.agentindex.ai/)
- [x402.direct API docs](https://x402.direct/docs)
- [Run402 docs](https://docs.run402.com/)
- Merit Systems [developer catalog](https://www.merit.systems/developers), x402scan [discovery spec](https://github.com/Merit-Systems/x402scan/blob/main/docs/DISCOVERY.md) and [OpenAPI](https://www.x402scan.com/openapi.json)
- [EXVIV x402 directory](https://exviv.com/x402)
