import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { createWalletClient, encodeDeployData, getAddress, http, type Abi, type Address, type Hex } from "viem";
import { baseSepolia } from "viem/chains";
import { privateKeyToAccount } from "viem/accounts";
import { ChainError, EXPECTED_CHAIN_ID, authorizeInternalWrite, baseSepoliaRpcUrl, createBaseSepoliaClient } from "./chain.js";
import { signerAddress } from "./telegraph.js";

export const TELEGRAPH_DIAMOND = "0x5a2324aA18613FAD4e44bDF0d6c73Ec1f6D87ff8" as Address;
export const RECEIVER_ARTIFACT_SHA256 = "6E4F6FB865D6A30378712233A0B84AAF9B55F713F326E05C8CA5FE96901C05FC";

type ReceiverArtifact = { abi: Abi; bytecode: Hex };

export function loadReceiverArtifact(): ReceiverArtifact {
  try {
    const path = fileURLToPath(new URL("./contracts/PRAMASubnetReceiver.json", import.meta.url));
    const contents = readFileSync(path);
    if (createHash("sha256").update(contents).digest("hex").toUpperCase() !== RECEIVER_ARTIFACT_SHA256) throw new Error("artifact digest mismatch");
    const parsed = JSON.parse(contents.toString("utf8")) as Partial<ReceiverArtifact>;
    if (!Array.isArray(parsed.abi) || typeof parsed.bytecode !== "string" || parsed.bytecode === "0x") throw new Error("artifact missing deployment bytecode");
    return { abi: parsed.abi as Abi, bytecode: parsed.bytecode as Hex };
  } catch {
    throw new ChainError("RECEIVER_ARTIFACT_MISSING", "certified subnet receiver artifact is unavailable");
  }
}

function requireBase(chainId: number) {
  if (chainId !== EXPECTED_CHAIN_ID) throw new ChainError("CHAIN_ID_MISMATCH", "Base Sepolia is required");
}

export async function receiverDeploymentPreflight(privateKey: string | undefined, internalToken: string | undefined) {
  authorizeInternalWrite(internalToken);
  const signer = signerAddress(privateKey);
  if (!signer) throw new ChainError("CHAIN_UNAVAILABLE", "gateway signer is unavailable");
  const account = getAddress(signer);
  const artifact = loadReceiverArtifact();
  const client = createBaseSepoliaClient();
  try {
    const chainId = await client.getChainId();
    requireBase(chainId);
    const data = encodeDeployData({ abi: artifact.abi, bytecode: artifact.bytecode, args: [TELEGRAPH_DIAMOND] });
    const [balance, gasPrice, gas] = await Promise.all([
      client.getBalance({ address: account }),
      client.getGasPrice(),
      client.estimateGas({ account, data, value: 0n }),
    ]);
    if (balance <= gas * gasPrice) throw new ChainError("INSUFFICIENT_GAS_FUNDS", "signer balance does not cover deployment gas");
    return { chain_id: chainId, signer_address: account, telegraph_diamond: TELEGRAPH_DIAMOND, artifact_sha256: RECEIVER_ARTIFACT_SHA256, bytecode_present: true, value_wei: "0", gas_estimate: gas.toString(), gas_price_wei: gasPrice.toString(), estimated_cost_wei: (gas * gasPrice).toString(), balance_wei: balance.toString(), status: "READY" as const, data, gas };
  } catch (error) {
    if (error instanceof ChainError) throw error;
    throw new ChainError("CHAIN_UNAVAILABLE", "receiver deployment preflight failed");
  }
}

/** The only G8-B write primitive: certified receiver bytecode, exact Diamond constructor, zero value. */
export async function deployExactSubnetReceiver(privateKey: string | undefined, internalToken: string | undefined) {
  const prepared = await receiverDeploymentPreflight(privateKey, internalToken);
  if (!privateKey) throw new ChainError("CHAIN_UNAVAILABLE", "gateway signer is unavailable");
  const account = privateKeyToAccount(privateKey as Hex);
  const wallet = createWalletClient({ account, chain: baseSepolia, transport: http(baseSepoliaRpcUrl()) });
  const txHash = await wallet.sendTransaction({ account, data: prepared.data, value: 0n, gas: prepared.gas });
  return { tx_hash: txHash, chain_id: prepared.chain_id, telegraph_diamond: TELEGRAPH_DIAMOND, artifact_sha256: RECEIVER_ARTIFACT_SHA256 };
}

export async function readSubnetReceiverDeployment(txHash: Hex) {
  const client = createBaseSepoliaClient();
  try {
    const receipt = await client.getTransactionReceipt({ hash: txHash });
    const transaction = await client.getTransaction({ hash: txHash });
    if (receipt.status !== "success" || !receipt.contractAddress || receipt.blockNumber === null || transaction.to !== null || transaction.value !== 0n) return { status: "FAILED" as const, failure_code: "RECEIVER_DEPLOYMENT_RECEIPT_MISMATCH" };
    const address = getAddress(receipt.contractAddress);
    const artifact = loadReceiverArtifact();
    const [code, diamond, responseHash] = await Promise.all([
      client.getCode({ address }),
      client.readContract({ address, abi: artifact.abi, functionName: "TELEGRAPH_DIAMOND" }),
      client.readContract({ address, abi: artifact.abi, functionName: "responseHash", args: [22n] }),
    ]);
    if (!code || code === "0x" || getAddress(diamond as string) !== TELEGRAPH_DIAMOND) return { status: "FAILED" as const, failure_code: "RECEIVER_RUNTIME_MISMATCH" };
    return { status: "CONFIRMED" as const, contract_address: address, block_number: receipt.blockNumber.toString(), block_hash: receipt.blockHash, gas_used: receipt.gasUsed.toString(), effective_gas_price: receipt.effectiveGasPrice.toString(), total_gas_cost: (receipt.gasUsed * receipt.effectiveGasPrice).toString(), code_present: true, telegraph_diamond: getAddress(diamond as string), response_hash_job_22: responseHash as Hex };
  } catch {
    return { status: "PENDING" as const };
  }
}
