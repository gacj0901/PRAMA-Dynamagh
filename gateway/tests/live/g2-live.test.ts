import assert from "node:assert/strict";
import test from "node:test";

const gateway = process.env.GATEWAY_URL ?? "http://gateway:8081";

test("G2 live routed Telegraph request has verified provenance", async () => {
  const response = await fetch(`${gateway}/ask`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ query: "What is the current price of Bitcoin in USD?", context: {}, causal_request_id: "g2-live-test" }),
  });
  assert.equal(response.status, 200);
  const payload = await response.json() as Record<string, unknown>;
  assert.ok(payload.miner_id);
  assert.ok(payload.miner_name);
  assert.ok(payload.intent);
  assert.notEqual(payload.result, null);
  assert.ok(Number(payload.cost_usd) > 0);
  assert.ok(Number(payload.duration_ms) >= 0);
  assert.match(String(payload.signal_hash), /^0x/);
  const signal = await fetch(`${gateway}/signals/${payload.signal_hash}`);
  assert.equal(signal.status, 200);
});
