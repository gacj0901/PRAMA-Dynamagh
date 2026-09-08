import assert from "node:assert/strict";
import test from "node:test";
import { BASE_SEPOLIA, BASE_SEPOLIA_USDC, GatewayError, signerAddress, validatePayment } from "../../src/telegraph.js";
test("missing key has no signer", () => assert.equal(signerAddress(), null));
test("accepts Base Sepolia USDC within cap", () => assert.equal(validatePayment({ network: BASE_SEPOLIA, asset: BASE_SEPOLIA_USDC, amount: "50000" }, "0.05").amount_usdc, "0.050000"));
test("rejects budget excess", () => assert.throws(() => validatePayment({ network: BASE_SEPOLIA, asset: BASE_SEPOLIA_USDC, amount: "50001" }, "0.05"), (e) => (e as GatewayError).code === "PAYMENT_BUDGET_EXCEEDED"));
test("explicit unlimited authority accepts any valid USDC requirement", () => assert.equal(validatePayment({ network: BASE_SEPOLIA, asset: BASE_SEPOLIA_USDC, amount: "500000000000" }, null).amount_usdc, "500000.000000"));
test("rejects wrong network", () => assert.throws(() => validatePayment({ network: "eip155:1", asset: BASE_SEPOLIA_USDC, amount: "1" }, "1")));
