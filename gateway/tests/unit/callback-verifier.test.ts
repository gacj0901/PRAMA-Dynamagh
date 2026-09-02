import assert from "node:assert/strict";
import test from "node:test";
import { encodeAbiParameters, keccak256, type Hex } from "viem";
import { canonicalOnChainData, decodeTerminalOnChainData, hashOnChainData, TRANSITION_TO_TERMINAL_SELECTOR, verifyCallbackResponse, verifyTerminalCallback } from "../../src/callback-verifier.js";

const response = {
  addresses: ["0x0000000000000000000000000000000000000001" as const],
  integers: [980000n, 20000n],
  strings: ["24.75", "67.0", "2t"],
  bools: [true, false],
};
const terminalEnvelope = [
  { type: "uint256" }, { type: "bytes32" }, { type: "address" }, { type: "bool" },
  { type: "tuple", components: [{ name: "addresses", type: "address[]" }, { name: "integers", type: "uint256[]" }, { name: "strings", type: "string[]" }, { name: "bools", type: "bool[]" }] },
  { type: "string" },
] as const;

function terminalCalldata() {
  const body = encodeAbiParameters(terminalEnvelope, [22n, `0x${"11".repeat(32)}`, "0x0000000000000000000000000000000000000002", true, response, ""]);
  return `${TRANSITION_TO_TERMINAL_SELECTOR}${body.slice(2)}` as Hex;
}

test("extracts OnChainData from exact terminal calldata and hashes canonical ABI bytes", () => {
  const decoded = decodeTerminalOnChainData(terminalCalldata());
  assert.deepEqual(decoded, response);
  assert.equal(canonicalOnChainData(decoded), canonicalOnChainData(response));
  assert.equal(hashOnChainData(decoded), keccak256(canonicalOnChainData(response)));
});

test("rejects non-terminal calldata and compares callback storage independently", async () => {
  assert.throws(() => decodeTerminalOnChainData("0x12345678" as Hex), /TERMINAL_CALLDATA_INVALID/);
  const expected = hashOnChainData(response);
  const client = { readContract: async () => expected };
  const valid = await verifyCallbackResponse(client, "0x0000000000000000000000000000000000000003", 22n, terminalCalldata());
  assert.equal(valid.status, "VALID");
  const invalid = await verifyCallbackResponse({ readContract: async () => `0x${"00".repeat(32)}` }, "0x0000000000000000000000000000000000000003", 22n, terminalCalldata());
  assert.equal(invalid.status, "INVALID");
});

test("verifies only a Diamond terminal transaction and classifies callback delivery failures", async () => {
  const expected = hashOnChainData(response);
  const client = {
    getTransaction: async () => ({ to: "0x0000000000000000000000000000000000000002" as const, input: terminalCalldata() }),
    getCode: async () => "0x6000" as Hex,
    readContract: async () => expected,
  };
  assert.equal((await verifyTerminalCallback(client, "0x0000000000000000000000000000000000000002", "0x0000000000000000000000000000000000000003", 22n, `0x${"22".repeat(32)}` as Hex)).status, "VALID");
  assert.equal((await verifyTerminalCallback({ ...client, readContract: async () => `0x${"00".repeat(32)}` as Hex }, "0x0000000000000000000000000000000000000002", "0x0000000000000000000000000000000000000003", 22n, `0x${"22".repeat(32)}` as Hex)).failure_code, "CALLBACK_NOT_DELIVERED");
  assert.equal((await verifyTerminalCallback({ ...client, getCode: async () => "0x" as Hex }, "0x0000000000000000000000000000000000000002", "0x0000000000000000000000000000000000000003", 22n, `0x${"22".repeat(32)}` as Hex)).failure_code, "RECEIVER_CODE_MISSING");
});
