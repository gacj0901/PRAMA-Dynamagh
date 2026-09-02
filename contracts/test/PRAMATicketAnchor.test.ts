import assert from "node:assert/strict";
import test from "node:test";
import { network } from "hardhat";

const fixtureHash = "0x444acabb98edd4c2f7c788ccdcc9991a475029f57feb4841ceb9ea3ccf97c00a";
const anotherHash = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const zeroHash = `0x${"00".repeat(32)}`;
const zeroAddress = "0x0000000000000000000000000000000000000000";

async function deployed() {
  const connection = await network.create();
  const [operator, outsider] = await connection.ethers.getSigners();
  const anchor = await connection.ethers.deployContract("PRAMATicketAnchor", [operator.address]);
  await anchor.waitForDeployment();
  return { anchor, connection, operator, outsider };
}

test("configures the operator and rejects a zero constructor operator", async () => {
  const { anchor, connection, operator } = await deployed();
  try {
    assert.equal(await anchor.operator(), operator.address);
    await assert.rejects(
      connection.ethers.deployContract("PRAMATicketAnchor", [zeroAddress]),
      /ZeroOperator/,
    );
  } finally { await connection.close(); }
});

test("anchors the fixture hash, records the block, and emits the exact event", async () => {
  const { anchor, connection, operator } = await deployed();
  try {
    const receipt = await (await anchor.anchor(fixtureHash)).wait();
    assert.equal(await anchor.isAnchored(fixtureHash), true);
    const block = await anchor.anchoredAtBlock(fixtureHash);
    assert.ok(block > 0n);
    const events = receipt!.logs.map((log: unknown) => {
      try { return anchor.interface.parseLog(log as never); } catch { return null; }
    }).filter(Boolean);
    const event = events.find((entry) => entry!.name === "TicketAnchored");
    assert.ok(event);
    assert.equal(event!.args.ticketHash, fixtureHash);
    assert.equal(event!.args.operator, operator.address);
    assert.equal(event!.args.blockNumber, block);
  } finally { await connection.close(); }
});

test("rejects a zero hash and unauthorized caller", async () => {
  const { anchor, connection, outsider } = await deployed();
  try {
    await assert.rejects(anchor.anchor(zeroHash), /ZeroTicketHash/);
    await assert.rejects(anchor.connect(outsider).anchor(fixtureHash), /Unauthorized/);
  } finally { await connection.close(); }
});

test("rejects duplicate anchors without changing the first block", async () => {
  const { anchor, connection } = await deployed();
  try {
    await (await anchor.anchor(fixtureHash)).wait();
    const initialBlock = await anchor.anchoredAtBlock(fixtureHash);
    await assert.rejects(anchor.anchor(fixtureHash), /AlreadyAnchored/);
    assert.equal(await anchor.anchoredAtBlock(fixtureHash), initialBlock);
  } finally { await connection.close(); }
});

test("anchors independent ticket hashes independently", async () => {
  const { anchor, connection } = await deployed();
  try {
    await (await anchor.anchor(fixtureHash)).wait();
    await (await anchor.anchor(anotherHash)).wait();
    assert.equal(await anchor.isAnchored(fixtureHash), true);
    assert.equal(await anchor.isAnchored(anotherHash), true);
    assert.ok(await anchor.anchoredAtBlock(fixtureHash) > 0n);
    assert.ok(await anchor.anchoredAtBlock(anotherHash) > 0n);
  } finally { await connection.close(); }
});
