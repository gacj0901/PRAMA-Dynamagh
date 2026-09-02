import {
  decodeAbiParameters,
  encodeAbiParameters,
  getAddress,
  isHex,
  keccak256,
  type Address,
  type Hex,
} from "viem";

export type OnChainData = {
  addresses: readonly Address[];
  integers: readonly bigint[];
  strings: readonly string[];
  bools: readonly boolean[];
};

export const TRANSITION_TO_TERMINAL_SELECTOR = "0x07098705" as Hex;
const onChainDataParameter = [{
  type: "tuple",
  components: [
    { name: "addresses", type: "address[]" },
    { name: "integers", type: "uint256[]" },
    { name: "strings", type: "string[]" },
    { name: "bools", type: "bool[]" },
  ],
}] as const;
const responseHashAbi = [{
  type: "function",
  name: "responseHash",
  stateMutability: "view",
  inputs: [{ name: "jobId", type: "uint256" }],
  outputs: [{ type: "bytes32" }],
}] as const;

function normaliseTuple(value: unknown): OnChainData {
  const tuple = value as { addresses?: Address[]; integers?: bigint[]; strings?: string[]; bools?: boolean[]; 0?: Address[]; 1?: bigint[]; 2?: string[]; 3?: boolean[] };
  return {
    addresses: (tuple.addresses ?? tuple[0] ?? []).map(getAddress),
    integers: tuple.integers ?? tuple[1] ?? [],
    strings: tuple.strings ?? tuple[2] ?? [],
    bools: tuple.bools ?? tuple[3] ?? [],
  };
}

export function canonicalOnChainData(response: OnChainData): Hex {
  return encodeAbiParameters(onChainDataParameter, [response]) as Hex;
}

export function hashOnChainData(response: OnChainData): Hex {
  return keccak256(canonicalOnChainData(response));
}

/**
 * Decode the OnChainData tuple from the exact observed terminal selector.
 * The Telegraph terminal envelope has protocol-owned prefix fields; scanning
 * ABI-valid dynamic tuple boundaries lets this verifier retain the response
 * commitment without inventing meaning for those unrelated fields.
 */
export function decodeTerminalOnChainData(calldata: Hex): OnChainData {
  if (!isHex(calldata) || calldata.slice(0, 10).toLowerCase() !== TRANSITION_TO_TERMINAL_SELECTOR) throw new Error("TERMINAL_CALLDATA_INVALID");
  const payload = calldata.slice(10);
  for (let offset = 0; offset + 128 <= payload.length; offset += 64) {
    const words = [0, 1, 2, 3].map((index) => BigInt(`0x${payload.slice(offset + index * 64, offset + (index + 1) * 64)}`));
    if (words.some((word) => word < 128n || word % 32n !== 0n)) continue;
    const tail = `0x${payload.slice(offset)}` as Hex;
    const wrapped = `0x${"00".repeat(31)}20${tail.slice(2)}` as Hex;
    try {
      const [decoded] = decodeAbiParameters(onChainDataParameter, wrapped);
      const response = normaliseTuple(decoded);
      const canonicalTail = canonicalOnChainData(response).slice(66);
      if (tail.slice(2, 2 + canonicalTail.length) !== canonicalTail) continue;
      return response;
    } catch {
      // Not an ABI-valid OnChainData tuple boundary; continue scanning.
    }
  }
  throw new Error("TERMINAL_RESPONSE_UNAVAILABLE");
}

export async function verifyCallbackResponse(
  client: { readContract: (request: unknown) => Promise<unknown> },
  callbackAddress: Address,
  jobId: bigint,
  terminalCalldata: Hex,
) {
  const response = decodeTerminalOnChainData(terminalCalldata);
  const expected = hashOnChainData(response);
  const stored = await client.readContract({ address: getAddress(callbackAddress), abi: responseHashAbi, functionName: "responseHash", args: [jobId] }) as Hex;
  return { response, expected_response_hash: expected, stored_response_hash: stored, status: stored.toLowerCase() === expected.toLowerCase() ? "VALID" : "INVALID" };
}

export async function verifyTerminalCallback(
  client: {
    getTransaction: (request: { hash: Hex }) => Promise<{ to: Address | null; input: Hex }>;
    getCode: (request: { address: Address }) => Promise<Hex | undefined>;
    readContract: (request: any) => Promise<unknown>;
  },
  diamond: Address,
  receiver: Address,
  jobId: bigint,
  terminalTxHash: Hex,
) {
  const transaction = await client.getTransaction({ hash: terminalTxHash });
  if (!transaction.to || getAddress(transaction.to) !== getAddress(diamond)) return { status: "INVALID", failure_code: "TERMINAL_CALLDATA_INVALID" as const };
  const code = await client.getCode({ address: getAddress(receiver) });
  if (!code || code === "0x") return { status: "INVALID", failure_code: "RECEIVER_CODE_MISSING" as const };
  let response: OnChainData;
  try { response = decodeTerminalOnChainData(transaction.input); }
  catch { return { status: "INVALID", failure_code: "TERMINAL_CALLDATA_INVALID" as const }; }
  const expected = hashOnChainData(response);
  const stored = await client.readContract({ address: getAddress(receiver), abi: responseHashAbi, functionName: "responseHash", args: [jobId] }) as Hex;
  if (stored.toLowerCase() === `0x${"00".repeat(32)}`) return { status: "INVALID", failure_code: "CALLBACK_NOT_DELIVERED" as const, expected_response_hash: expected, stored_response_hash: stored };
  if (stored.toLowerCase() !== expected.toLowerCase()) return { status: "INVALID", failure_code: "CALLBACK_HASH_MISMATCH" as const, expected_response_hash: expected, stored_response_hash: stored };
  return { status: "VALID" as const, response, expected_response_hash: expected, stored_response_hash: stored };
}
