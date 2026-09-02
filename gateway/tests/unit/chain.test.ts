import assert from "node:assert/strict";
import test from "node:test";
import { ChainError, PREFLIGHT_TICKET_HASH, authorizeInternalWrite, deploymentPreflight, encodeAnchorCalldata, validateTicketHash } from "../../src/chain.js";

const testSigner = "0x0000000000000000000000000000000000000001" as const;
const failing = (code: string) => (error: unknown) => error instanceof ChainError && error.code === code;

test("accepts only non-zero bytes32 ticket hashes and encodes anchor calldata", () => {
  assert.equal(validateTicketHash(PREFLIGHT_TICKET_HASH), PREFLIGHT_TICKET_HASH);
  assert.match(encodeAnchorCalldata(PREFLIGHT_TICKET_HASH), /^0xeecdf927/);
  assert.throws(() => validateTicketHash("0x1234"), failing("ANCHOR_TICKET_HASH_INVALID"));
  assert.throws(() => validateTicketHash(`0x${"00".repeat(32)}`), failing("ANCHOR_TICKET_HASH_ZERO"));
});

test("fails preflight with CHAIN_ID_MISMATCH before any estimate", async () => {
  await assert.rejects(
    deploymentPreflight(undefined, PREFLIGHT_TICKET_HASH, {
      signer: testSigner,
      client: { getChainId: async () => 1, getBalance: async () => 0n, getGasPrice: async () => 0n, estimateGas: async () => 0n },
    }),
    failing("CHAIN_ID_MISMATCH"),
  );
});

test("fails preflight with CHAIN_UNAVAILABLE when RPC cannot provide a chain id", async () => {
  await assert.rejects(
    deploymentPreflight(undefined, PREFLIGHT_TICKET_HASH, {
      signer: testSigner,
      client: { getChainId: async () => { throw new Error("offline"); }, getBalance: async () => 0n, getGasPrice: async () => 0n, estimateGas: async () => 0n },
    }),
    failing("CHAIN_UNAVAILABLE"),
  );
});

test("reports INSUFFICIENT_GAS_FUNDS without any signing when balance is below preflight cost", async () => {
  const result = await deploymentPreflight(undefined, PREFLIGHT_TICKET_HASH, {
    signer: testSigner,
    client: { getChainId: async () => 84532, getBalance: async () => 0n, getGasPrice: async () => 2n, estimateGas: async () => 10n },
  });
  assert.equal(result.status, "INSUFFICIENT_GAS_FUNDS");
  assert.equal(result.gas_funds_sufficient, false);
  assert.equal(result.deployment_gas_cost_wei, "20");
});

test("fails preflight with ANCHOR_ARTIFACT_MISSING when artifact loading fails", async () => {
  await assert.rejects(
    deploymentPreflight(undefined, PREFLIGHT_TICKET_HASH, {
      signer: testSigner,
      loadArtifact: () => { throw new ChainError("ANCHOR_ARTIFACT_MISSING", "missing"); },
    }),
    failing("ANCHOR_ARTIFACT_MISSING"),
  );
});

test("rejects restricted anchor writes unless the internal token matches", () => {
  const original = process.env.PRAMA_GATEWAY_INTERNAL_TOKEN;
  try {
    process.env.PRAMA_GATEWAY_INTERNAL_TOKEN = "test-only-internal-token";
    assert.throws(() => authorizeInternalWrite(undefined), failing("CHAIN_WRITE_UNAUTHORIZED"));
    assert.throws(() => authorizeInternalWrite("wrong"), failing("CHAIN_WRITE_UNAUTHORIZED"));
    assert.doesNotThrow(() => authorizeInternalWrite("test-only-internal-token"));
  } finally {
    if (original === undefined) delete process.env.PRAMA_GATEWAY_INTERNAL_TOKEN;
    else process.env.PRAMA_GATEWAY_INTERNAL_TOKEN = original;
  }
});
