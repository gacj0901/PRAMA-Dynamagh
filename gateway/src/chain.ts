import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import {
  createPublicClient,
  createWalletClient,
  decodeEventLog,
  encodeDeployData,
  encodeFunctionData,
  formatEther,
  getAddress,
  http,
  isAddress,
  isHex,
  type Abi,
  type Address,
  type Hex,
} from "viem";
import { baseSepolia } from "viem/chains";
import { privateKeyToAccount } from "viem/accounts";
import { signerAddress } from "./telegraph.js";

export const EXPECTED_CHAIN_ID = 84532;
export const DEFAULT_BASE_SEPOLIA_RPC_URL = "https://sepolia.base.org";
export const PREFLIGHT_TICKET_HASH = "0x444acabb98edd4c2f7c788ccdcc9991a475029f57feb4841ceb9ea3ccf97c00a";

type AnchorArtifact = { abi: Abi; bytecode: Hex };
type PreflightClient = {
  getChainId: () => Promise<number>;
  getBalance: (parameters: { address: Address }) => Promise<bigint>;
  getGasPrice: () => Promise<bigint>;
  estimateGas: (parameters: { account: Address; data: Hex }) => Promise<bigint>;
};
type PreflightDependencies = { client?: PreflightClient; loadArtifact?: () => AnchorArtifact; signer?: Address };
export type ChainFailureCode = "CHAIN_ID_MISMATCH" | "CHAIN_UNAVAILABLE" | "ANCHOR_ARTIFACT_MISSING" | "ANCHOR_TICKET_HASH_INVALID" | "ANCHOR_TICKET_HASH_ZERO" | "ANCHOR_CONTRACT_INVALID" | "ANCHOR_CONTRACT_UNAVAILABLE" | "CHAIN_WRITE_UNAUTHORIZED" | "ANCHOR_ALREADY_EXISTS" | "INSUFFICIENT_GAS_FUNDS";

export class ChainError extends Error {
  constructor(readonly code: ChainFailureCode, message: string) { super(message); }
}

export function baseSepoliaRpcUrl(): string {
  return process.env.BASE_SEPOLIA_RPC_URL ?? DEFAULT_BASE_SEPOLIA_RPC_URL;
}

export function createBaseSepoliaClient(rpcUrl = baseSepoliaRpcUrl()) {
  return createPublicClient({ chain: baseSepolia, transport: http(rpcUrl) });
}

export function validateTicketHash(value: string): Hex {
  if (!isHex(value) || value.length !== 66) throw new ChainError("ANCHOR_TICKET_HASH_INVALID", "ticket hash must be a 32-byte hex value");
  if (value === `0x${"00".repeat(32)}`) throw new ChainError("ANCHOR_TICKET_HASH_ZERO", "ticket hash must not be zero");
  return value as Hex;
}

export function loadAnchorArtifact(): AnchorArtifact {
  try {
    const path = fileURLToPath(new URL("./contracts/PRAMATicketAnchor.json", import.meta.url));
    const parsed = JSON.parse(readFileSync(path, "utf8")) as Partial<AnchorArtifact>;
    if (!Array.isArray(parsed.abi) || typeof parsed.bytecode !== "string" || parsed.bytecode === "0x") throw new Error("invalid artifact");
    return { abi: parsed.abi as Abi, bytecode: parsed.bytecode as Hex };
  } catch {
    throw new ChainError("ANCHOR_ARTIFACT_MISSING", "compiled anchor artifact is unavailable");
  }
}

export function configuredAnchorAddress(): Address | null {
  const value = process.env.PRAMA_TICKET_ANCHOR_ADDRESS;
  if (!value) return null;
  if (!isAddress(value)) throw new ChainError("ANCHOR_CONTRACT_INVALID", "configured anchor contract address is invalid");
  return getAddress(value);
}

async function chainIdOrUnavailable(client: { getChainId: () => Promise<number> }): Promise<number> {
  try { return await client.getChainId(); }
  catch { throw new ChainError("CHAIN_UNAVAILABLE", "Base Sepolia RPC is unavailable"); }
}

export async function chainHealth(privateKey?: string) {
  const client = createBaseSepoliaClient();
  const chainId = await chainIdOrUnavailable(client);
  return {
    rpc_status: "ok",
    chain_id: chainId,
    signer_address: signerAddress(privateKey),
    anchor_contract: configuredAnchorAddress(),
  };
}

export async function deploymentPreflight(privateKey: string | undefined, ticketHash = PREFLIGHT_TICKET_HASH, dependencies: PreflightDependencies = {}) {
  const signer = dependencies.signer ?? signerAddress(privateKey);
  if (!signer) throw new ChainError("CHAIN_UNAVAILABLE", "gateway signer is unavailable");
  const signerAccount = getAddress(signer);
  const hash = validateTicketHash(ticketHash);
  const artifact = (dependencies.loadArtifact ?? loadAnchorArtifact)();
  const client = (dependencies.client ?? createBaseSepoliaClient()) as PreflightClient;
  const actualChainId = await chainIdOrUnavailable(client);
  if (actualChainId !== EXPECTED_CHAIN_ID) throw new ChainError("CHAIN_ID_MISMATCH", `expected chain ${EXPECTED_CHAIN_ID}, received ${actualChainId}`);
  try {
    const deploymentData = encodeDeployData({ abi: artifact.abi, bytecode: artifact.bytecode, args: [signerAccount] });
    const anchorCalldata = encodeFunctionData({ abi: artifact.abi, functionName: "anchor", args: [hash] });
    void anchorCalldata;
    const [balance, gasPrice, deploymentGasEstimate] = await Promise.all([
      client.getBalance({ address: signerAccount }),
      client.getGasPrice(),
      client.estimateGas({ account: signerAccount, data: deploymentData }),
    ]);
    const deploymentGasCost = gasPrice * deploymentGasEstimate;
    return {
      expected_chain_id: EXPECTED_CHAIN_ID,
      actual_chain_id: actualChainId,
      signer_address: signerAccount,
      signer_balance_wei: balance.toString(),
      signer_balance_eth: formatEther(balance),
      artifact_loaded: true,
      bytecode_present: artifact.bytecode !== "0x",
      deployment_gas_estimate: deploymentGasEstimate.toString(),
      deployment_gas_price_wei: gasPrice.toString(),
      deployment_gas_cost_wei: deploymentGasCost.toString(),
      gas_funds_sufficient: balance >= deploymentGasCost,
      status: balance >= deploymentGasCost ? "READY" : "INSUFFICIENT_GAS_FUNDS",
    };
  } catch (error) {
    if (error instanceof ChainError) throw error;
    throw new ChainError("CHAIN_UNAVAILABLE", "Base Sepolia RPC preflight failed");
  }
}

export function encodeAnchorCalldata(ticketHash: string): Hex {
  const artifact = loadAnchorArtifact();
  return encodeFunctionData({ abi: artifact.abi, functionName: "anchor", args: [validateTicketHash(ticketHash)] });
}

export async function readAnchorState(ticketHash: string, anchorAddress = configuredAnchorAddress()) {
  const address = anchorAddress;
  if (!address) throw new ChainError("ANCHOR_CONTRACT_INVALID", "anchor contract is not configured");
  const artifact = loadAnchorArtifact();
  const hash = validateTicketHash(ticketHash);
  const client = createBaseSepoliaClient();
  try {
    const [operator, anchored, anchoredAtBlock] = await Promise.all([
      client.readContract({ address, abi: artifact.abi, functionName: "operator" }),
      client.readContract({ address, abi: artifact.abi, functionName: "isAnchored", args: [hash] }),
      client.readContract({ address, abi: artifact.abi, functionName: "anchoredAtBlock", args: [hash] }),
    ]);
    return { operator: operator as Address, is_anchored: anchored as boolean, anchored_at_block: String(anchoredAtBlock) };
  } catch { throw new ChainError("CHAIN_UNAVAILABLE", "anchor state could not be read"); }
}

export function authorizeInternalWrite(candidate: string | undefined): void {
  const expected = process.env.PRAMA_GATEWAY_INTERNAL_TOKEN;
  if (!expected || !candidate || candidate !== expected) throw new ChainError("CHAIN_WRITE_UNAUTHORIZED", "internal anchor authorization is required");
}

type ExactAnchorPreflight = { signer: Address; address: Address; hash: Hex; data: Hex; gas: bigint; gas_price: bigint; balance: bigint; chain_id: number };

/** Authenticated, exact and read-only. It never creates a signer transaction. */
export async function preflightExactAnchor(privateKey: string | undefined, internalToken: string | undefined, ticketHash: string): Promise<ExactAnchorPreflight> {
  authorizeInternalWrite(internalToken);
  const account = privateKey ? privateKeyToAccount(privateKey as `0x${string}`) : null;
  if (!account) throw new ChainError("CHAIN_UNAVAILABLE", "gateway signer is unavailable");
  const signer = getAddress(account.address);
  const address = configuredAnchorAddress();
  if (!address) throw new ChainError("ANCHOR_CONTRACT_INVALID", "anchor contract is not configured");
  const hash = validateTicketHash(ticketHash);
  const artifact = loadAnchorArtifact();
  const client = createBaseSepoliaClient();
  const chainId = await chainIdOrUnavailable(client);
  if (chainId !== EXPECTED_CHAIN_ID) throw new ChainError("CHAIN_ID_MISMATCH", "Base Sepolia is required");
  try {
    const [code, operator, anchored] = await Promise.all([
      client.getCode({ address }),
      client.readContract({ address, abi: artifact.abi, functionName: "operator" }),
      client.readContract({ address, abi: artifact.abi, functionName: "isAnchored", args: [hash] }),
    ]);
    if (!code || code === "0x") throw new ChainError("ANCHOR_CONTRACT_UNAVAILABLE", "anchor contract code is unavailable");
    if (getAddress(operator as string) !== signer) throw new ChainError("CHAIN_WRITE_UNAUTHORIZED", "gateway signer is not the anchor operator");
    if (anchored as boolean) throw new ChainError("ANCHOR_ALREADY_EXISTS", "ticket hash is already anchored");
    const data = encodeFunctionData({ abi: artifact.abi, functionName: "anchor", args: [hash] });
    const value = 0n;
    const [balance, gasPrice, gas] = await Promise.all([
      client.getBalance({ address: signer }),
      client.getGasPrice(),
      client.estimateGas({ account: signer, to: address, data, value }),
    ]);
    if (balance <= gas * gasPrice) throw new ChainError("INSUFFICIENT_GAS_FUNDS", "signer balance does not cover anchor gas");
    return { signer, address, hash, data, gas, gas_price: gasPrice, balance, chain_id: chainId };
  } catch (error) {
    if (error instanceof ChainError) throw error;
    throw new ChainError("CHAIN_UNAVAILABLE", "anchor preflight or submission failed");
  }
}

/** The only G6 write primitive: exact anchor(bytes32), exact configured contract, zero value. */
export async function submitExactAnchor(privateKey: string | undefined, internalToken: string | undefined, ticketHash: string) {
  const prepared = await preflightExactAnchor(privateKey, internalToken, ticketHash);
  const account = privateKeyToAccount(privateKey as `0x${string}`);
  const wallet = createWalletClient({ account, chain: baseSepolia, transport: http(baseSepoliaRpcUrl()) });
  const txHash = await wallet.sendTransaction({ account, to: prepared.address, data: prepared.data, value: 0n, gas: prepared.gas });
  return { tx_hash: txHash, chain_id: prepared.chain_id, contract_address: prepared.address };
}

/** Read-only receipt, event and state verification for the one exact anchor operation. */
export async function readExactAnchorReceipt(privateKey: string | undefined, ticketHash: string, txHash: string) {
  const signer = signerAddress(privateKey);
  const address = configuredAnchorAddress();
  const hash = validateTicketHash(ticketHash);
  if (!signer || !address || !isHex(txHash) || txHash.length !== 66) throw new ChainError("ANCHOR_CONTRACT_INVALID", "anchor receipt parameters are invalid");
  const artifact = loadAnchorArtifact();
  const client = createBaseSepoliaClient();
  let receipt;
  try { receipt = await client.getTransactionReceipt({ hash: txHash as Hex }); }
  catch { return { status: "PENDING" as const }; }
  const transaction = await client.getTransaction({ hash: txHash as Hex });
  if (receipt.status !== "success") return { status: "FAILED" as const, failure_code: "ANCHOR_TX_REVERTED" };
  if (!transaction.to || getAddress(transaction.to) !== address || transaction.value !== 0n || receipt.blockNumber === null) return { status: "FAILED" as const, failure_code: "ANCHOR_RECEIPT_MISMATCH" };
  const event = receipt.logs.map((log) => {
    try { return decodeEventLog({ abi: artifact.abi, eventName: "TicketAnchored", data: log.data, topics: log.topics }); }
    catch { return null; }
  }).find((entry) => {
    if (!entry) return false;
    const args = entry.args as unknown as { operator: string; ticketHash: Hex; blockNumber: bigint };
    return getAddress(args.operator) === getAddress(signer) && args.ticketHash === hash && args.blockNumber === receipt.blockNumber;
  });
  if (!event) return { status: "FAILED" as const, failure_code: "ANCHOR_EVENT_MISMATCH" };
  const state = await readAnchorState(hash, address);
  if (!state.is_anchored || state.anchored_at_block !== receipt.blockNumber.toString()) return { status: "FAILED" as const, failure_code: "ANCHOR_STATE_MISMATCH" };
  return {
    status: "CONFIRMED" as const,
    tx_hash: txHash,
    block_number: receipt.blockNumber.toString(),
    block_hash: receipt.blockHash,
    gas_used: receipt.gasUsed.toString(),
    effective_gas_price: receipt.effectiveGasPrice.toString(),
    total_gas_cost: (receipt.gasUsed * receipt.effectiveGasPrice).toString(),
    event_verified: true,
    anchored_at_block: state.anchored_at_block,
  };
}
