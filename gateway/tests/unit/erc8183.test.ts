import assert from "node:assert/strict";
import test from "node:test";
import { STORM_ALERT_INTENT, STORM_ALERT_INTENT_ID, STORM_ALERT_PARAMS, ZERO_ADDRESS, configuredCallback, guardedCallback } from "../../src/erc8183.js";
import { keccak256, stringToHex } from "viem";

test("uses the exact documented STORM_ALERT ERC-8183 fixture", () => {
  assert.equal(STORM_ALERT_INTENT, "STORM_ALERT");
  assert.equal(STORM_ALERT_INTENT_ID, keccak256(stringToHex("STORM_ALERT")));
  assert.deepEqual(STORM_ALERT_PARAMS, { addresses: [], integers: [], strings: ["24.75", "67.0", "2t", "", ""], bools: [false] });
  assert.equal(ZERO_ADDRESS, "0x0000000000000000000000000000000000000000");
});

test("allows only zero or a configured callback with runtime code", async () => {
  const prior = process.env.TELEGRAPH_CALLBACK_CONTRACT_ADDRESS;
  try {
    delete process.env.TELEGRAPH_CALLBACK_CONTRACT_ADDRESS;
    assert.equal(configuredCallback(), ZERO_ADDRESS);
    process.env.TELEGRAPH_CALLBACK_CONTRACT_ADDRESS = "0x0000000000000000000000000000000000000004";
    await assert.rejects(guardedCallback({ getCode: async () => "0x" }), /no runtime code/);
    assert.deepEqual(await guardedCallback({ getCode: async () => "0x6000" }), { callback: "0x0000000000000000000000000000000000000004", codePresent: true });
  } finally {
    if (prior === undefined) delete process.env.TELEGRAPH_CALLBACK_CONTRACT_ADDRESS;
    else process.env.TELEGRAPH_CALLBACK_CONTRACT_ADDRESS = prior;
  }
});
