import express from "express";
import { ChainError, chainHealth, deploymentPreflight, preflightExactAnchor, readAnchorState, readExactAnchorReceipt, submitExactAnchor } from "./chain.js";
import { GatewayError, normalize, paidFetch, signerAddress } from "./telegraph.js";

const app = express();
const port = Number(process.env.PORT ?? 8081);
const baseUrl = (process.env.TELEGRAPH_BASE_URL ?? "https://devnode.telegraphprotocol.com").replace(/\/$/, "");
const privateKey = process.env.TELEGRAPH_SIGNER_PRIVATE_KEY;
const maxPayment = process.env.TELEGRAPH_MAX_PAYMENT_USDC ?? "0.05";
const signer = signerAddress(privateKey);

app.use(express.json({ limit: "256kb" }));

app.get("/health", (_request, response) => {
  response.json({ status: "ok", service: "prama-dynamagh-gateway", signer_address: signer });
});
function chainFailure(response: express.Response, error: unknown) {
  const known = error instanceof ChainError ? error : new ChainError("CHAIN_UNAVAILABLE", "chain preflight failed");
  const status = known.code === "CHAIN_ID_MISMATCH" || known.code === "ANCHOR_ALREADY_EXISTS" || known.code === "INSUFFICIENT_GAS_FUNDS" ? 409 : known.code === "CHAIN_UNAVAILABLE" || known.code === "ANCHOR_CONTRACT_UNAVAILABLE" ? 503 : known.code === "CHAIN_WRITE_UNAUTHORIZED" ? 403 : 400;
  response.status(status).json({ code: known.code });
}
app.get("/chain/health", async (_request, response) => {
  try { response.json(await chainHealth(privateKey)); }
  catch (error) { chainFailure(response, error); }
});
app.get("/chain/preflight", async (request, response) => {
  const ticketHash = typeof request.query.ticket_hash === "string" ? request.query.ticket_hash : undefined;
  try { response.json(await deploymentPreflight(privateKey, ticketHash)); }
  catch (error) { chainFailure(response, error); }
});
app.get("/chain/ticket-anchors/:ticketHash", async (request, response) => {
  try { response.json(await readAnchorState(request.params.ticketHash)); }
  catch (error) { chainFailure(response, error); }
});
app.get("/chain/ticket-anchors/:ticketHash/transactions/:txHash", async (request, response) => {
  try { response.json(await readExactAnchorReceipt(privateKey, request.params.ticketHash, request.params.txHash)); }
  catch (error) { chainFailure(response, error); }
});
app.post("/chain/ticket-anchors/preflight", async (request, response) => {
  try {
    const ticketHash = request.body?.ticket_hash;
    if (typeof ticketHash !== "string") return response.status(400).json({ code: "ANCHOR_TICKET_HASH_INVALID" });
    const result = await preflightExactAnchor(privateKey, request.header("x-prama-internal-token") ?? undefined, ticketHash);
    response.json({ chain_id: result.chain_id, contract_address: result.address, gas_estimate: result.gas.toString(), gas_price_wei: result.gas_price.toString(), estimated_cost_wei: (result.gas * result.gas_price).toString(), balance_wei: result.balance.toString(), status: "READY" });
  } catch (error) { chainFailure(response, error); }
});
app.post("/chain/ticket-anchors", async (request, response) => {
  try {
    const ticketHash = request.body?.ticket_hash;
    if (typeof ticketHash !== "string") return response.status(400).json({ code: "ANCHOR_TICKET_HASH_INVALID" });
    response.status(202).json(await submitExactAnchor(privateKey, request.header("x-prama-internal-token") ?? undefined, ticketHash));
  } catch (error) { chainFailure(response, error); }
});
async function proxy(path: string, response: express.Response) { try { const upstream = await fetch(baseUrl + path); response.status(upstream.status).json(await upstream.json()); } catch { response.status(503).json({ code: "TELEGRAPH_UNAVAILABLE" }); } }
app.get("/miners", (_req, res) => void proxy("/api/miners", res));
app.get("/intents", (_req, res) => void proxy("/engine/v1/intents", res));
app.get("/signals/:signalHash", (req, res) => void proxy(`/engine/v1/signal/${encodeURIComponent(req.params.signalHash)}`, res));
app.post("/ask", async (req, res) => {
  const { query, context = {}, causal_request_id, budget_usdc } = req.body ?? {};
  if (!query || !causal_request_id) return res.status(400).json({ code: "TELEGRAPH_INVALID_RESPONSE" });
  if (!privateKey) return res.status(402).json({ code: "PAYMENT_REQUIRED" });
  try { const cap = budget_usdc ? String(Math.min(Number(maxPayment), Number(budget_usdc))) : maxPayment; const paymentClient = paidFetch(privateKey, cap); const upstream = await paymentClient.fetcher(`${baseUrl}/engine/v1/ask`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ query, context }) }); if (!upstream.ok) return res.status(upstream.status).json({ code: upstream.status === 402 ? "PAYMENT_REQUIRED" : "TELEGRAPH_REQUEST_FAILED" }); const raw = await upstream.json() as Record<string, unknown>; const normalized = normalize(raw, causal_request_id, paymentClient.payment()); if (!normalized.signal_hash) return res.status(502).json({ code: "TELEGRAPH_INVALID_RESPONSE" }); const signal = await fetch(`${baseUrl}/engine/v1/signal/${normalized.signal_hash}`); if (!signal.ok) return res.status(502).json({ code: "SIGNAL_VERIFICATION_FAILED" }); return res.json(normalized); } catch (error) { const known = error instanceof GatewayError ? error.code : "PAYMENT_FAILED"; return res.status(400).json({ code: known }); }
});

app.listen(port, () => {
  console.log(`PRAMA-Dynamagh gateway listening on ${port}`);
});
