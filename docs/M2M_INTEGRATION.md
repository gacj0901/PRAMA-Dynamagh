# PRAMA-Dynamagh M2M integration

The M2M rail accepts one authenticated agent request and returns a durable,
traceable result surface. The client does not need to know about G12, G13,
Telegraph, x402, or PRAMAgraph to submit a request.

```bash
curl -X POST https://prama-dynamagh.up.railway.app/v1/m2m/mandates \
  -H "Authorization: Bearer $PRAMA_M2M_API_TOKEN" \
  -H "Idempotency-Key: $(uuidgen)" \
  -H "Content-Type: application/json" \
  -d '{"intent":"CRYPTO_PRICE","request":"What is the current price of ETH in USD?"}'
```

```python
import os, uuid, requests
r = requests.post("https://prama-dynamagh.up.railway.app/v1/m2m/mandates",
  headers={"Authorization": f"Bearer {os.environ['PRAMA_M2M_API_TOKEN']}",
           "Idempotency-Key": str(uuid.uuid4())},
  json={"intent": "CRYPTO_PRICE", "request": "What is the current price of ETH in USD?"})
result = r.json()
print(result["request_id"], result["mandate_id"], result["result_endpoint"])
```

```ts
const result = await fetch("https://prama-dynamagh.up.railway.app/v1/m2m/mandates", {
  method: "POST",
  headers: { Authorization: `Bearer ${process.env.PRAMA_M2M_API_TOKEN}`,
    "Idempotency-Key": crypto.randomUUID(), "Content-Type": "application/json" },
  body: JSON.stringify({ intent: "CRYPTO_PRICE", request: "What is the current price of ETH in USD?" })
}).then(r => r.json());
console.log(result.request_id, result.mandate_id, result.result_endpoint);
```

The response includes `request_id`, `mandate_id`, `status`,
`result_endpoint`, and `ticket_endpoint` when a Ticket exists. Repeating the
same `Idempotency-Key` returns the original Mandate and cannot create a second
paid acquisition.

The persisted lineage is:

```text
external agent → authenticated M2M request → Mandate(M2M)
→ AcquisitionTask → Telegraph → Miner → Evidence → Decision → Ticket
```

Each request is attributed with `request_id`, `source_principal`,
`external_agent_id`, `authenticated_at`, `mandate_id`, and intent. Miner,
signal, evidence, decision, and Ticket identifiers remain available through
the result and Ticket endpoints.

## Initial consumers to approach

These are integration targets, not fabricated users or synthetic traffic:

1. Telegraph ecosystem builders that already need a governed intelligence call.
2. Trading and market agents needing bounded price or market observations.
3. Procurement agents comparing external supplier or asset data.
4. Research agents that need provenance before acting on a result.
5. Autonomous workflow runners that require a durable result/Ticket callback.

The adoption message is: **Send an agent request to PRAMA-Dynamagh; it acquires
intelligence through Telegraph and returns a structurally evaluated, traceable
decision artifact.**
