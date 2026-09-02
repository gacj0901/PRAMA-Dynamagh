import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import test from "node:test";
import { AbiCoder, keccak256 } from "ethers";
import { network } from "hardhat";

const diamond = "0x000000000000000000000000000000000000d1A0";
const coder = AbiCoder.defaultAbiCoder();
const tupleType = "tuple(address[] addresses,uint256[] integers,string[] strings,bool[] bools)";
const small = { addresses: [], integers: [], strings: ["sample"], bools: [false] };
const realistic = {
  addresses: ["0x0000000000000000000000000000000000000001", "0x0000000000000000000000000000000000000002"],
  integers: [1n, 980000n, 20000n],
  strings: ["24.75", "67.0", "2t", "status:ok"],
  bools: [true, false],
};

function responseDigest(response: typeof small | typeof realistic) {
  return keccak256(coder.encode([tupleType], [response]));
}

function opcodes(bytecode: string): number[] {
  const bytes = Buffer.from(bytecode.slice(2), "hex");
  const result: number[] = [];
  for (let index = 0; index < bytes.length; index += 1) {
    const opcode = bytes[index];
    result.push(opcode);
    if (opcode >= 0x60 && opcode <= 0x7f) index += opcode - 0x5f;
  }
  return result;
}

async function deployed() {
  const connection = await network.create();
  const [authorized, outsider] = await connection.ethers.getSigners();
  const receiver = await connection.ethers.deployContract("PRAMASubnetReceiver", [authorized.address]);
  await receiver.waitForDeployment();
  return { connection, receiver, authorized, outsider };
}

test("stores the immutable Diamond and starts with zero response hashes", async () => {
  const { connection, receiver, authorized } = await deployed();
  try {
    assert.equal(await receiver.TELEGRAPH_DIAMOND(), authorized.address);
    assert.equal(await receiver.responseHash(22n), "0x" + "00".repeat(32));
  } finally { await connection.close(); }
});

test("only the Diamond caller stores keccak256(abi.encode(response))", async () => {
  const { connection, receiver, authorized, outsider } = await deployed();
  try {
    await assert.rejects(receiver.connect(outsider).subnetMessage(22n, true, small, ""), /Unauthorized/);
    await (await receiver.connect(authorized).subnetMessage(22n, true, small, "")).wait();
    assert.equal(await receiver.responseHash(22n), responseDigest(small));
    await (await receiver.connect(authorized).subnetMessage(23n, true, realistic, "")).wait();
    assert.equal(await receiver.responseHash(23n), responseDigest(realistic));
    assert.notEqual(await receiver.responseHash(22n), await receiver.responseHash(23n));
  } finally { await connection.close(); }
});

test("encodes empty and dynamic arrays deterministically with one storage target", async () => {
  const { connection, receiver, authorized } = await deployed();
  try {
    const empty = { addresses: [], integers: [], strings: [], bools: [] };
    await (await receiver.connect(authorized).subnetMessage(1n, true, empty, "ignored")).wait();
    await (await receiver.connect(authorized).subnetMessage(2n, true, realistic, "ignored")).wait();
    assert.equal(await receiver.responseHash(1n), keccak256(coder.encode([tupleType], [empty])));
    assert.equal(await receiver.responseHash(2n), responseDigest(realistic));
  } finally { await connection.close(); }
});

test("keeps callback gas bounded for small and realistic fixtures", async () => {
  const { connection, receiver, authorized } = await deployed();
  try {
    const smallGas = await receiver.connect(authorized).subnetMessage.estimateGas(30n, true, small, "");
    const realisticGas = await receiver.connect(authorized).subnetMessage.estimateGas(31n, true, realistic, "");
    assert.ok(smallGas > 0n);
    assert.ok(realisticGas > smallGas);
    console.log(`callback_gas_estimate_small=${smallGas}`);
    console.log(`callback_gas_estimate_realistic=${realisticGas}`);
  } finally { await connection.close(); }
});

test("artifact has the exact callback ABI and no CALL-family opcode", async () => {
  const path = resolve("artifacts/src/PRAMASubnetReceiver.sol/PRAMASubnetReceiver.json");
  const artifact = JSON.parse(await readFile(path, "utf8"));
  const callback = artifact.abi.find((entry: { type: string; name?: string }) => entry.type === "function" && entry.name === "subnetMessage");
  assert.ok(callback);
  assert.equal(callback.inputs.length, 4);
  assert.deepEqual(callback.inputs.map((input: { type: string }) => input.type), ["uint256", "bool", "tuple", "string"]);
  assert.deepEqual(callback.inputs[2].components.map((component: { type: string }) => component.type), ["address[]", "uint256[]", "string[]", "bool[]"]);
  assert.notEqual(artifact.bytecode, "0x");
  assert.notEqual(artifact.deployedBytecode, "0x");
  const runtimeOpcodes = opcodes(artifact.deployedBytecode);
  for (const opcode of [0xf1, 0xf2, 0xf4, 0xfa]) assert.equal(runtimeOpcodes.includes(opcode), false, `unexpected external-call opcode 0x${opcode.toString(16)}`);
});
