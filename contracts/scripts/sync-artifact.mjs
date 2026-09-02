import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";

const source = resolve(process.argv[2] ?? "artifacts/src/PRAMATicketAnchor.sol/PRAMATicketAnchor.json");
const destination = resolve(process.argv[3] ?? "../gateway/src/contracts/PRAMATicketAnchor.json");
const compiled = JSON.parse(await readFile(source, "utf8"));
if (!Array.isArray(compiled.abi) || typeof compiled.bytecode !== "string" || compiled.bytecode === "0x") {
  throw new Error("compiled anchor artifact lacks ABI or deployment bytecode");
}
const artifact = `${JSON.stringify({ abi: compiled.abi, bytecode: compiled.bytecode }, null, 2)}\n`;
await mkdir(dirname(destination), { recursive: true });
await writeFile(destination, artifact, "utf8");
