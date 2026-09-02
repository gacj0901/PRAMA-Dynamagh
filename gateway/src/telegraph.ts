import { x402Client, wrapFetchWithPayment } from "@x402/fetch";
import { ExactEvmScheme, toClientEvmSigner } from "@x402/evm";
import { privateKeyToAccount } from "viem/accounts";

export const BASE_SEPOLIA = "eip155:84532";
export const BASE_SEPOLIA_USDC = "0x036cbd53842c5426634e7929541ec2318f3dcf7e";
export type PaymentInfo = { network: string; amount_usdc: string };

export class GatewayError extends Error { constructor(readonly code: string, message: string) { super(message); } }
export function signerAddress(key?: string): string | null { return key ? privateKeyToAccount(key as `0x${string}`).address : null; }
export function validatePayment(requirement: { network: string; asset: string; amount?: string; maxAmountRequired?: string }, limit: string): PaymentInfo {
  if (requirement.network !== BASE_SEPOLIA) throw new GatewayError("PAYMENT_NETWORK_UNSUPPORTED", "payment network is unsupported");
  if (requirement.asset.toLowerCase() !== BASE_SEPOLIA_USDC) throw new GatewayError("PAYMENT_ASSET_MISMATCH", "payment asset is unsupported");
  const amount = requirement.amount ?? requirement.maxAmountRequired;
  if (!amount || !/^\d+$/.test(amount)) throw new GatewayError("PAYMENT_FAILED", "payment amount is invalid");
  const atomicLimit = BigInt(Math.round(Number(limit) * 1_000_000));
  if (BigInt(amount) > atomicLimit) throw new GatewayError("PAYMENT_BUDGET_EXCEEDED", "payment exceeds configured budget");
  return { network: requirement.network, amount_usdc: (Number(BigInt(amount)) / 1_000_000).toFixed(6) };
}
export function paidFetch(key: string, limit: string): { fetcher: typeof fetch; payment: () => PaymentInfo | null } {
  const account = privateKeyToAccount(key as `0x${string}`);
  let payment: PaymentInfo | null = null;
  const client = new x402Client().register(BASE_SEPOLIA, new ExactEvmScheme(toClientEvmSigner(account)));
  client.registerPolicy((_version, requirements) => {
    const accepted = requirements.filter((r) => {
      try { payment = validatePayment(r as never, limit); return true; } catch { return false; }
    });
    if (!accepted.length) validatePayment(requirements[0] as never, limit);
    return accepted;
  });
  return { fetcher: wrapFetchWithPayment(fetch, client), payment: () => payment };
}
export function normalize(raw: Record<string, unknown>, causal_request_id: string, payment: PaymentInfo | null) {
  const miner = (raw.miner ?? raw.provider ?? {}) as Record<string, unknown>;
  return { causal_request_id, miner_id: raw.miner_id ?? miner.id ?? null, miner_name: raw.miner_name ?? miner.name ?? null, intent: raw.intent ?? null, signal_hash: raw.signal_hash ?? raw.signalHash ?? null, result: raw.result ?? null, cost_usd: raw.cost_usd ?? raw.cost ?? null, duration_ms: raw.duration_ms ?? raw.duration ?? null, reasoning: raw.reasoning ?? null, warnings: raw.warnings ?? [], timestamp: raw.timestamp ?? new Date().toISOString(), payment };
}
