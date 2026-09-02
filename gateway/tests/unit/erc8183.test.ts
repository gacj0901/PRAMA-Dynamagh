import assert from "node:assert/strict";
import test from "node:test";
import { STORM_ALERT_INTENT, STORM_ALERT_INTENT_ID, STORM_ALERT_PARAMS, ZERO_ADDRESS } from "../../src/erc8183.js";
import { keccak256, stringToHex } from "viem";

test("uses the exact documented STORM_ALERT ERC-8183 fixture", () => {
  assert.equal(STORM_ALERT_INTENT, "STORM_ALERT");
  assert.equal(STORM_ALERT_INTENT_ID, keccak256(stringToHex("STORM_ALERT")));
  assert.deepEqual(STORM_ALERT_PARAMS, { addresses: [], integers: [], strings: ["24.75", "67.0", "2t", "", ""], bools: [false] });
  assert.equal(ZERO_ADDRESS, "0x0000000000000000000000000000000000000000");
});
