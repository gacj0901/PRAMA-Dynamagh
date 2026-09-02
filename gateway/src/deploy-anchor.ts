import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { createWalletClient, encodeDeployData, getAddress, http } from "viem";
import { privateKeyToAccount } from "viem/accounts";
import { baseSepolia } from "viem/chains";
import { EXPECTED_CHAIN_ID, baseSepoliaRpcUrl, createBaseSepoliaClient, loadAnchorArtifact } from "./chain.js";

const expectedSigner = "0xC92b5ec74dca3EeE0A615dE026C3F3756cd18FB6";

function blocked(code: string): never { throw new Error(code); }

async function main() {
  const privateKey = process.env.TELEGRAPH_SIGNER_PRIVATE_KEY;
  if (!privateKey) blocked("DEPLOYMENT_BLOCKED_SIGNER_UNAVAILABLE");
  const account = privateKeyToAccount(privateKey as `0x${string}`);
  const signer = getAddress(account.address);
  if (signer !== getAddress(expectedSigner)) blocked("DEPLOYMENT_BLOCKED_SIGNER_MISMATCH");

  const artifactPath = fileURLToPath(new URL("./contracts/PRAMATicketAnchor.json", import.meta.url));
  const artifactHash = createHash("sha256").update(readFileSync(artifactPath)).digest("hex").toUpperCase();
  if (artifactHash !== "380F12CB7C8DA7A9C90BF995EE8D824B97F9A579E29D574F86CA98F63E56FD5E") blocked("DEPLOYMENT_BLOCKED_ARTIFACT_CHANGED");
  const artifact = loadAnchorArtifact();
  if (artifact.bytecode === "0x") blocked("DEPLOYMENT_BLOCKED_BYTECODE_MISSING");

  const client = createBaseSepoliaClient();
  const chainId = await client.getChainId();
  if (chainId !== EXPECTED_CHAIN_ID) blocked("DEPLOYMENT_BLOCKED_CHAIN_ID_MISMATCH");
  const data = encodeDeployData({ abi: artifact.abi, bytecode: artifact.bytecode, args: [signer] });
  const value = 0n;
  const [balanceBefore, gasPrice, gasEstimate] = await Promise.all([
    client.getBalance({ address: signer }),
    client.getGasPrice(),
    client.estimateGas({ account: signer, data, value }),
  ]);
  const estimatedCost = gasEstimate * gasPrice;
  if (balanceBefore <= estimatedCost) blocked("DEPLOYMENT_BLOCKED_INSUFFICIENT_GAS_FUNDS");

  const wallet = createWalletClient({ account, chain: baseSepolia, transport: http(baseSepoliaRpcUrl()) });
  const txHash = await wallet.sendTransaction({ account, data, value, gas: gasEstimate });
  const receipt = await client.waitForTransactionReceipt({ hash: txHash, confirmations: 1, timeout: 120_000 });
  const transaction = await client.getTransaction({ hash: txHash });
  if (receipt.status !== "success" || !receipt.contractAddress || receipt.blockNumber === null || transaction.to !== null || transaction.value !== value) {
    blocked("DEPLOYMENT_RECEIPT_VERIFICATION_FAILED");
  }
  const code = await client.getCode({ address: receipt.contractAddress });
  const operator = await client.readContract({ address: receipt.contractAddress, abi: artifact.abi, functionName: "operator" });
  if (!code || code === "0x" || getAddress(operator as string) !== signer) blocked("DEPLOYMENT_RUNTIME_VERIFICATION_FAILED");
  const balanceAfter = await client.getBalance({ address: signer });
  console.log(JSON.stringify({
    chain_id: chainId,
    address: receipt.contractAddress,
    deployment_tx_hash: txHash,
    deployment_block: receipt.blockNumber.toString(),
    operator: signer,
    artifact_sha256: artifactHash,
    transaction_status: receipt.status,
    transaction_to: transaction.to,
    transaction_value_wei: transaction.value.toString(),
    gas_used: receipt.gasUsed.toString(),
    effective_gas_price: receipt.effectiveGasPrice.toString(),
    total_gas_cost: (receipt.gasUsed * receipt.effectiveGasPrice).toString(),
    balance_before: balanceBefore.toString(),
    balance_after: balanceAfter.toString(),
    code_present: true,
    runtime_verification: "PASS",
  }));
}

main().catch((error) => { console.error(error instanceof Error ? error.message : "DEPLOYMENT_BLOCKED"); process.exitCode = 1; });
