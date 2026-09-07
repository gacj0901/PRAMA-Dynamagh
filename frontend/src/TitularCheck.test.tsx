// @vitest-environment jsdom
import { act } from "react";
import { createRoot, Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TitularCheck, fetchReceipt, receiptHash, verificationLabel, Receipt } from "./TitularCheck";
import receiptFixture from "../tests/fixtures/receipt.json";

const hash = "a".repeat(64);
const path = `/titular-check/${hash}-prama-dynamagh`;
let container: HTMLDivElement, root: Root, callback: (token: string) => void;
let receipt: Receipt;
let transport: ReturnType<typeof vi.fn>;

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  receipt = structuredClone(receiptFixture);
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  window.turnstile = { render: vi.fn((_element, options) => { callback = options.callback as typeof callback; return "fixture-widget"; }), remove: vi.fn() };
  transport = vi.fn(async (url: string) => {
    if (url.endsWith("/config")) return new Response(JSON.stringify({ site_key: "fixture-site" }));
    if (url.endsWith("/challenge")) return new Response(JSON.stringify({ access_token: "fixture-access" }));
    if (url.endsWith("/acknowledge")) return new Response(JSON.stringify({ status: "ACKNOWLEDGED" }));
    return new Response(JSON.stringify(receipt));
  });
  vi.stubGlobal("fetch", transport);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.unstubAllGlobals(); delete window.turnstile; });
async function render(value = path) { await act(async () => root.render(<TitularCheck path={value} />)); }
async function passGate() { await act(async () => callback("ephemeral-challenge")); }
async function click(text: string) { await act(async () => { Array.from(container.querySelectorAll("button")).find(button => button.textContent === text)!.click(); }); }

describe("Titular Check", () => {
  it("requires human presence before loading or revealing the receipt", async () => {
    await render();
    expect(container.textContent).toContain("TITULAR CHECK");
    expect(container.textContent).not.toContain("PERMIT");
    expect(transport).toHaveBeenCalledTimes(1);
    expect(transport.mock.calls[0][0]).toBe("/api/v1/titular-check/config");
    await passGate();
    for (const text of ["PRAMA—DYNAMAGH", "PRAMA-Dynamagh", "PERMIT", "0.010000", "Fixture intelligence provider", "ADMITTED", "STRUCTURALLY_ADMISSIBLE", "RESPONSE HASH", receipt.response_hash, "VERIFIED", "0 ms"]) expect(container.textContent).toContain(text);
  });
  it("VERIFY AGAIN makes only a GET; acknowledgement is separate", async () => {
    await render(); await passGate(); transport.mockClear();
    await click("VERIFY AGAIN");
    expect(transport).toHaveBeenCalledTimes(1);
    expect(transport.mock.calls[0]).toEqual([`/api/v1${path}`, { method: "GET", cache: "no-store", credentials: "omit", headers: { Authorization: "Bearer fixture-access" } }]);
    expect(container.textContent).not.toContain("ACKNOWLEDGED");
    await click("ACKNOWLEDGE");
    expect(container.textContent).toContain("ACKNOWLEDGED");
    expect(container.textContent).toContain("not approval of the action");
  });
  it.each(["/titular-check/1", `/titular-check/${hash}`, `/titular-check/${hash}-wrong`, "/titular-check"])("rejects invalid locator without transport: %s", async invalid => {
    expect(receiptHash(invalid)).toBeNull(); await render(invalid);
    expect(container.textContent).toContain("INVALID RECEIPT"); expect(transport).not.toHaveBeenCalled();
  });
  it("shows not found for a gated missing hash", async () => {
    await render(); transport.mockResolvedValueOnce(new Response("{}", { status: 404 })); await passGate();
    expect(container.textContent).toContain("RECEIPT NOT FOUND");
  });
  it("fails closed without Turnstile configuration", async () => {
    transport.mockResolvedValue(new Response("{}", { status: 503 })); await render();
    expect(container.textContent).toContain("HUMAN PRESENCE UNAVAILABLE");
    expect(container.textContent).not.toContain("PERMIT");
  });
  it("does not fetch a receipt without an access grant", async () => {
    expect(await fetchReceipt(path, "")).toEqual({ kind: "HUMAN PRESENCE REQUIRED" }); expect(transport).not.toHaveBeenCalled();
  });
  it.each(["payload_hash_match", "source_artifacts_match"] as const)("rejects %s failure", key => {
    receipt.verification[key] = false; expect(verificationLabel(receipt, hash)).toBe("VERIFICATION FAILED");
  });
  it("checks returned and reconstructed identity against the URL", () => {
    receipt.verification.reconstructed_hash = "0x" + "b".repeat(64);
    expect(verificationLabel(receipt, hash)).toBe("VERIFICATION FAILED");
    receipt.verification.reconstructed_hash = receipt.response_hash; receipt.response_hash = "0x" + "b".repeat(64);
    expect(verificationLabel(receipt, hash)).toBe("VERIFICATION FAILED");
  });
  it("unknown verification cannot be VERIFIED", () => {
    receipt.verification.status = "UNAVAILABLE";
    expect(verificationLabel(receipt, hash)).toBe("VERIFICATION UNAVAILABLE");
  });
  it("failed replay cannot be VERIFIED", () => {
    receipt.replay.status = "INVALID";
    expect(verificationLabel(receipt, hash)).toBe("VERIFICATION FAILED");
  });
});
