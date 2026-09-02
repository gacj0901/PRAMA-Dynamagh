import {
  createPublicClient, createWalletClient, decodeEventLog, encodeFunctionData,
  getAddress, http, keccak256, parseUnits, stringToHex, type Address, type Hex,
} from "viem";
import { baseSepolia } from "viem/chains";
import { privateKeyToAccount } from "viem/accounts";
import { EXPECTED_CHAIN_ID, baseSepoliaRpcUrl, ChainError, authorizeInternalWrite } from "./chain.js";
import { signerAddress } from "./telegraph.js";

export const TELEGRAPH_DIAMOND = "0x5a2324aA18613FAD4e44bDF0d6c73Ec1f6D87ff8" as Address;
export const TELEGRAPH_USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e" as Address;
export const ZERO_ADDRESS = "0x0000000000000000000000000000000000000000" as Address;
export const STORM_ALERT_INTENT = "STORM_ALERT";
export const STORM_ALERT_INTENT_ID = keccak256(stringToHex(STORM_ALERT_INTENT));
export const STORM_ALERT_PARAMS = { addresses: [] as Address[], integers: [] as bigint[], strings: ["24.75", "67.0", "2t", "", ""], bools: [false] };

const diamondAbi = [
  { type: "function", name: "usdcToken", stateMutability: "view", inputs: [], outputs: [{ type: "address" }] },
  { type: "function", name: "getJobBasePrice", stateMutability: "view", inputs: [], outputs: [{ type: "uint256" }] },
  { type: "function", name: "escrowBalance", stateMutability: "view", inputs: [{ name: "agent", type: "address" }], outputs: [{ type: "uint256" }] },
  { type: "function", name: "depositUSDC", stateMutability: "nonpayable", inputs: [{ name: "amount", type: "uint256" }], outputs: [] },
  { type: "function", name: "createJob", stateMutability: "nonpayable", inputs: [{ name: "intentId", type: "bytes32" }, { name: "params", type: "tuple", components: [{ name: "addresses", type: "address[]" }, { name: "integers", type: "uint256[]" }, { name: "strings", type: "string[]" }, { name: "bools", type: "bool[]" }] }, { name: "callback", type: "address" }], outputs: [{ type: "uint256" }] },
  { type: "function", name: "cancelJob", stateMutability: "nonpayable", inputs: [{ name: "jobId", type: "uint256" }], outputs: [] },
  { type: "function", name: "getJob", stateMutability: "view", inputs: [{ name: "jobId", type: "uint256" }], outputs: [{ type: "tuple", components: [{ name: "agent", type: "address" }, { name: "intentId", type: "bytes32" }, { name: "callback", type: "address" }, { name: "budget", type: "uint256" }, { name: "minerPayment", type: "uint256" }, { name: "protocolFee", type: "uint256" }, { name: "state", type: "uint8" }, { name: "createdAt", type: "uint256" }] }] },
  { type: "function", name: "getJobOutput", stateMutability: "view", inputs: [{ name: "jobId", type: "uint256" }], outputs: [{ type: "bytes32" }] },
  { type: "event", name: "JobCreated", inputs: [{ name: "jobId", type: "uint256", indexed: true }, { name: "agent", type: "address", indexed: true }, { name: "intentId", type: "bytes32", indexed: false }, { name: "callback", type: "address", indexed: false }] },
  { type: "event", name: "JobTerminal", inputs: [{ name: "jobId", type: "uint256", indexed: true }, { name: "fee", type: "uint256", indexed: false }, { name: "minerPaid", type: "uint256", indexed: false }] },
] as const;
const erc20Abi = [
  { type: "function", name: "balanceOf", stateMutability: "view", inputs: [{ name: "account", type: "address" }], outputs: [{ type: "uint256" }] },
  { type: "function", name: "allowance", stateMutability: "view", inputs: [{ name: "owner", type: "address" }, { name: "spender", type: "address" }], outputs: [{ type: "uint256" }] },
  { type: "function", name: "approve", stateMutability: "nonpayable", inputs: [{ name: "spender", type: "address" }, { name: "amount", type: "uint256" }], outputs: [{ type: "bool" }] },
] as const;

type JobValue = { agent: Address; intentId: Hex; callback: Address; budget: bigint; minerPayment: bigint; protocolFee: bigint; state: number; createdAt: bigint };
export function configuredDiamond(): Address { return getAddress(process.env.TELEGRAPH_DIAMOND_ADDRESS ?? TELEGRAPH_DIAMOND); }
export function configuredUsdc(): Address { return getAddress(process.env.TELEGRAPH_USDC_ADDRESS ?? TELEGRAPH_USDC); }
export function maxJobBudgetMicro(): bigint { return parseUnits(process.env.ERC8183_MAX_JOB_BUDGET_USDC ?? "2.000000", 6); }
export function publicClient() { return createPublicClient({ chain: baseSepolia, transport: http(baseSepoliaRpcUrl()) }); }
function accountFor(privateKey: string | undefined) { if (!privateKey) throw new ChainError("CHAIN_UNAVAILABLE", "gateway signer is unavailable"); return privateKeyToAccount(privateKey as Hex); }
function requireExactFixture(intentId: string, params: typeof STORM_ALERT_PARAMS, callback: string) {
  if (intentId !== STORM_ALERT_INTENT_ID || callback.toLowerCase() !== ZERO_ADDRESS || JSON.stringify(params) !== JSON.stringify(STORM_ALERT_PARAMS)) throw new ChainError("ERC8183_FIXTURE_INVALID" as never, "only the fixed STORM_ALERT fixture is allowed");
}
async function requireBase(client: ReturnType<typeof publicClient>) { const id = await client.getChainId(); if (id !== EXPECTED_CHAIN_ID) throw new ChainError("CHAIN_ID_MISMATCH", "Base Sepolia is required"); return id; }

export async function erc8183Preflight(privateKey: string | undefined) {
  const signer = signerAddress(privateKey); if (!signer) throw new ChainError("CHAIN_UNAVAILABLE", "gateway signer is unavailable");
  const client = publicClient(), diamond = configuredDiamond(), usdc = configuredUsdc(), account = getAddress(signer);
  const chainId = await requireBase(client);
  const [diamondCode, usdcCode, token, price, escrow, usdcBalance, allowance, gasPrice, ethBalance] = await Promise.all([
    client.getCode({ address: diamond }), client.getCode({ address: usdc }), client.readContract({ address: diamond, abi: diamondAbi, functionName: "usdcToken" }), client.readContract({ address: diamond, abi: diamondAbi, functionName: "getJobBasePrice" }), client.readContract({ address: diamond, abi: diamondAbi, functionName: "escrowBalance", args: [account] }), client.readContract({ address: usdc, abi: erc20Abi, functionName: "balanceOf", args: [account] }), client.readContract({ address: usdc, abi: erc20Abi, functionName: "allowance", args: [account, diamond] }), client.getGasPrice(), client.getBalance({ address: account }),
  ]);
  if (!diamondCode || diamondCode === "0x" || !usdcCode || usdcCode === "0x") throw new ChainError("ERC8183_CONTRACT_UNAVAILABLE" as never, "Diamond or USDC code is unavailable");
  if (getAddress(token as string) !== usdc) throw new ChainError("ERC8183_USDC_MISMATCH" as never, "Diamond USDC token does not match configured USDC");
  if ((price as bigint) > maxJobBudgetMicro()) throw new ChainError("ERC8183_JOB_BUDGET_EXCEEDED" as never, "live job price exceeds configured cap");
  const topUp = (price as bigint) > (escrow as bigint) ? (price as bigint) - (escrow as bigint) : 0n;
  if ((usdcBalance as bigint) < topUp) throw new ChainError("ERC8183_INSUFFICIENT_USDC" as never, "signer lacks USDC for bounded escrow top-up");
  const approveData = encodeFunctionData({ abi: erc20Abi, functionName: "approve", args: [diamond, topUp] });
  const depositData = encodeFunctionData({ abi: diamondAbi, functionName: "depositUSDC", args: [topUp] });
  const createData = encodeFunctionData({ abi: diamondAbi, functionName: "createJob", args: [STORM_ALERT_INTENT_ID, STORM_ALERT_PARAMS, ZERO_ADDRESS] });
  const estimate = async (to: Address, data: Hex) => { try { return await client.estimateGas({ account, to, data, value: 0n }); } catch { return null; } };
  const [approveGas, depositGas, createGas] = await Promise.all([estimate(usdc, approveData), estimate(diamond, depositData), (escrow as bigint) >= (price as bigint) ? estimate(diamond, createData) : Promise.resolve(null)]);
  const gasNeed = [approveGas, depositGas, createGas].reduce<bigint>((sum, gas) => sum + (gas ?? 0n), 0n) * gasPrice;
  return { status: "READY", chain_id: chainId, diamond_address: diamond, usdc_address: usdc, diamond_code_present: true, usdc_code_present: true, diamond_usdc_token: getAddress(token as string), signer_address: account, signer_eth_balance_wei: ethBalance.toString(), signer_usdc_balance_micro: (usdcBalance as bigint).toString(), usdc_allowance_micro: (allowance as bigint).toString(), escrow_balance_micro: (escrow as bigint).toString(), job_base_price_micro: (price as bigint).toString(), budget_cap_micro: maxJobBudgetMicro().toString(), required_escrow_micro: (price as bigint).toString(), top_up_micro: topUp.toString(), intent_name: STORM_ALERT_INTENT, intent_id: STORM_ALERT_INTENT_ID, callback: ZERO_ADDRESS, estimated_approve_gas: approveGas?.toString() ?? null, estimated_deposit_gas: depositGas?.toString() ?? null, estimated_create_job_gas: createGas?.toString() ?? null, create_simulation_ready: (escrow as bigint) >= (price as bigint), signer_gas_sufficient: ethBalance > gasNeed };
}

async function exactWrite(privateKey: string | undefined, token: string | undefined, to: Address, data: Hex, expectedGas: bigint | null) {
  authorizeInternalWrite(token); const account = accountFor(privateKey); const client = publicClient(); await requireBase(client);
  const gas = expectedGas ?? await client.estimateGas({ account: account.address, to, data, value: 0n });
  const wallet = createWalletClient({ account, chain: baseSepolia, transport: http(baseSepoliaRpcUrl()) });
  return wallet.sendTransaction({ account, to, data, value: 0n, gas });
}
async function confirmedExactWrite(privateKey: string | undefined, token: string | undefined, to: Address, data: Hex, expectedGas: bigint | null) {
  const txHash = await exactWrite(privateKey, token, to, data, expectedGas);
  const receipt = await publicClient().waitForTransactionReceipt({ hash: txHash, timeout: 120_000, pollingInterval: 2_000 });
  if (receipt.status !== "success" || receipt.blockNumber === null) throw new ChainError("ERC8183_FUNDING_REVERTED" as never, "bounded ERC-8183 funding transaction reverted");
  return { tx_hash: txHash, block_number: receipt.blockNumber.toString(), gas_used: receipt.gasUsed.toString(), effective_gas_price: receipt.effectiveGasPrice.toString(), total_gas_cost: (receipt.gasUsed * receipt.effectiveGasPrice).toString() };
}
export async function approveTelegraphUsdc(privateKey: string | undefined, token: string | undefined, amount: bigint) {
  const p = await erc8183Preflight(privateKey); if (amount <= 0n || amount !== BigInt(p.top_up_micro)) throw new ChainError("ERC8183_AMOUNT_INVALID" as never, "approval must equal exact escrow top-up");
  return { ...await confirmedExactWrite(privateKey, token, configuredUsdc(), encodeFunctionData({ abi: erc20Abi, functionName: "approve", args: [configuredDiamond(), amount] }), null), amount: amount.toString() };
}
export async function depositTelegraphEscrow(privateKey: string | undefined, token: string | undefined, amount: bigint) {
  const p = await erc8183Preflight(privateKey); if (amount <= 0n || amount !== BigInt(p.top_up_micro) || BigInt(p.usdc_allowance_micro) < amount) throw new ChainError("ERC8183_AMOUNT_INVALID" as never, "deposit must equal approved exact escrow top-up");
  return { ...await confirmedExactWrite(privateKey, token, configuredDiamond(), encodeFunctionData({ abi: diamondAbi, functionName: "depositUSDC", args: [amount] }), null), amount: amount.toString() };
}
export async function createTelegraphJob(privateKey: string | undefined, token: string | undefined) {
  const p = await erc8183Preflight(privateKey); if (!p.create_simulation_ready) throw new ChainError("ERC8183_ESCROW_INSUFFICIENT" as never, "escrow must be funded before createJob");
  requireExactFixture(STORM_ALERT_INTENT_ID, STORM_ALERT_PARAMS, ZERO_ADDRESS);
  return { tx_hash: await exactWrite(privateKey, token, configuredDiamond(), encodeFunctionData({ abi: diamondAbi, functionName: "createJob", args: [STORM_ALERT_INTENT_ID, STORM_ALERT_PARAMS, ZERO_ADDRESS] }), BigInt(p.estimated_create_job_gas!)), chain_id: p.chain_id, diamond_address: p.diamond_address };
}
export async function cancelTelegraphJob(privateKey: string | undefined, token: string | undefined, jobId: bigint) {
  const job = await readTelegraphJob(jobId); if (job.state !== 0) throw new ChainError("ERC8183_CANCEL_INVALID" as never, "only Funded jobs may be cancelled");
  return confirmedExactWrite(privateKey, token, configuredDiamond(), encodeFunctionData({ abi: diamondAbi, functionName: "cancelJob", args: [jobId] }), null);
}
export async function readTelegraphJob(jobId: bigint) {
  const client = publicClient(), diamond = configuredDiamond(); await requireBase(client);
  const [raw, output] = await Promise.all([client.readContract({ address: diamond, abi: diamondAbi, functionName: "getJob", args: [jobId] }), client.readContract({ address: diamond, abi: diamondAbi, functionName: "getJobOutput", args: [jobId] })]);
  const job = raw as unknown as JobValue;
  return { job_id: jobId.toString(), agent: getAddress(job.agent), intent_id: job.intentId, callback: getAddress(job.callback), budget_micro: job.budget.toString(), miner_payment_micro: job.minerPayment.toString(), protocol_fee_micro: job.protocolFee.toString(), state: Number(job.state), created_at: job.createdAt.toString(), output_hash: output as Hex };
}
export async function readCreateReceipt(privateKey: string | undefined, txHash: Hex) {
  const signer = signerAddress(privateKey); if (!signer) throw new ChainError("CHAIN_UNAVAILABLE", "gateway signer is unavailable"); const client = publicClient();
  let receipt; try { receipt = await client.getTransactionReceipt({ hash: txHash }); } catch { return { status: "PENDING" as const }; }
  if (receipt.status !== "success") return { status: "FAILED" as const, failure_code: "ERC8183_CREATE_REVERTED" };
  const event = receipt.logs.map(log => { try { return decodeEventLog({ abi: diamondAbi, eventName: "JobCreated", data: log.data, topics: log.topics }); } catch { return null; } }).find(entry => entry && getAddress((entry.args as { agent: Address }).agent) === getAddress(signer) && (entry.args as { intentId: Hex }).intentId === STORM_ALERT_INTENT_ID && getAddress((entry.args as { callback: Address }).callback) === ZERO_ADDRESS);
  if (!event || receipt.blockNumber === null) return { status: "FAILED" as const, failure_code: "ERC8183_JOBCREATED_MISMATCH" };
  const args = event.args as { jobId: bigint }; return { status: "CONFIRMED" as const, job_id: args.jobId.toString(), block_number: receipt.blockNumber.toString(), tx_hash: txHash };
}
export async function findTerminalEvent(jobId: bigint, fromBlock: bigint) {
  const client = publicClient(); const logs = await client.getLogs({ address: configuredDiamond(), event: diamondAbi[9], args: { jobId }, fromBlock });
  const event = logs.at(-1); return event ? { tx_hash: event.transactionHash, block_number: event.blockNumber.toString(), event_verified: true } : null;
}
