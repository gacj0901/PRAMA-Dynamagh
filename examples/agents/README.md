# PRAMA Agent Access examples

These are native HTTP clients, not new execution engines. Nothing executes at
import time. Both implementations make one unpaid request, validate the current
x402 v2 challenge, invoke a caller-owned signer callback once, send one paid
request, privately checkpoint the 202 capability, and retrieve only its result.

Python needs httpx. TypeScript targets ES2022 with DOM types (Node 22+ fetch).
Use an audited x402 SDK in the signer callback to create PAYMENT-SIGNATURE from
the validated challenge. Keep keys in a wallet service or secure keystore;
never put keys, signatures or result capabilities in an LLM prompt or logs.
The callback receives the full challenge including resource/extensions; sign
the exact authorized amount, never the ceiling. This package intentionally does
not implement EIP-712 signing a second time.

Set policy from independently trusted configuration: network eip155:84532,
current USDC contract, recipient and domain; obtain the current values through
the service descriptor and unpaid challenge and approve them outside the LLM.
Defaults are not authorization. Base Sepolia is TESTNET, not mainnet.
Max request 0.05 USDC and max session 0.25 USDC correspond to 50000/250000
atomic units for this six-decimal asset. Clients are single-use; a signer shared
by multiple clients MUST enforce an aggregate session budget in durable state.
An in-memory client limit is not a cross-process spending ledger.

`checkpoint` MUST durably store its input privately, atomically and without
printing it. It is called before paid submission and immediately on 202, before
polling. A crash, timeout or ambiguous response must NOT trigger a new payment.
An unavailable checkpoint after 202 is an operator-recovery situation, not a
reason to pay again. These examples do not promise crash-atomic HTTP/storage.

Python: construct `PramaClient(policy=..., signer=..., checkpoint=...)`, then
call `client.request(requested_intent="WEB_SEARCH", query=actual_need)` only
after authorization. TypeScript exposes the same request method.
`frameworks.py` provides lazy optional LangChain and SmolAgents wrappers around
that exact client; neither wrapper contains signing or settlement code.

Inspect returned content as well as `consumer_result.status`. DELIVERED can
contain only part of a multi-acquisition workflow and does not prove correctness.
Governance fields and original evidence hashes remain available.

Discovery: https://prama-dynamagh.up.railway.app/agents.md
MCP (discovery only): https://prama-dynamagh.up.railway.app/mcp
