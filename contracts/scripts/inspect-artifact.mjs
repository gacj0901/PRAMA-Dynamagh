import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const source = resolve(process.argv[2] ?? "artifacts/src/PRAMATicketAnchor.sol/PRAMATicketAnchor.json");
const artifact = JSON.parse(await readFile(source, "utf8"));
console.log(JSON.stringify({
  abi_entries: Array.isArray(artifact.abi) ? artifact.abi.length : 0,
  deployment_bytecode_present: typeof artifact.bytecode === "string" && artifact.bytecode !== "0x",
  runtime_bytecode_present: typeof artifact.deployedBytecode === "string" && artifact.deployedBytecode !== "0x",
}));
