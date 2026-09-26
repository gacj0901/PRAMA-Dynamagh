import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";
import { afterEach, describe, expect, it, vi } from "vitest";

const html = readFileSync(fileURLToPath(new URL("../../index.html", import.meta.url)), "utf8");
const runtimeSource = readFileSync(fileURLToPath(new URL("../../public/v3-runtime.js", import.meta.url)), "utf8");
const openPage = () => new JSDOM(html, { url: "https://prama.test/", runScripts: "outside-only" });

afterEach(() => vi.restoreAllMocks());

describe("public dashboard history and runtime read model", () => {
  it("places history below Runtime in the left pipeline column and before persisted chain", () => {
    const dom = openPage();
    const { document } = dom.window;
    const history = document.querySelector(".pipeline-panel #executionHistoryRows");
    const runtime = document.querySelector(".pipeline-panel .runtime-inline");
    const chain = document.querySelector(".secondary h3");

    expect(history).not.toBeNull();
    expect(runtime.compareDocumentPosition(history) & dom.window.Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(history.closest(".miner-panel, .secondary")).toBeNull();
    expect(history.compareDocumentPosition(chain) & dom.window.Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(document.querySelectorAll(".pipeline-panel .pipe .step")).toHaveLength(6);
    expect(document.querySelector(".miner-panel > h2").textContent).toBe("Miner Responses");
    expect(document.querySelectorAll("table.origin tr[data-origin]")).toHaveLength(5);
    expect(document.querySelector('table.origin tr[data-origin="user"] td:first-child').textContent).toBe("USER");
    dom.window.close();
  });

  it("renders real history fields, stored Evidence SHA, truncated query and unknown delivery; refreshes every 12 seconds", async () => {
    const dom = openPage();
    const { document } = dom.window;
    const now = "2026-09-25T12:34:00+00:00";
    const hash = `0x${"a".repeat(64)}`;
    let activity = {
      processed_responses: 8,
      responses_with_evidence: 6,
      actual_spend_usdc: "0.010000",
      autonomous: { processed_responses: 3, responses_with_evidence: 2 },
      manual: { processed_responses: 2, responses_with_evidence: 1 },
      user: { processed_responses: 1, responses_with_evidence: 1 },
      m2m: { processed_responses: 2, responses_with_evidence: 2 },
      demand_origin: { external_user_driven: 3, manual: 2, m2m_inbound: 2, user: 1, fixture_canary: 0, unattributed_legacy: 0 },
      scope: { included_origins: ["MANUAL", "M2M", "USER"] },
      latest_miner_response: null,
      operational_ledger: { mandates: { ticketed: 1, total: 2, autonomous: 1 } },
      execution_history: [{
        time: now,
        origin: "M2M",
        client: "agent-17",
        intent: "CRYPTO_PRICE",
        query: "What is the persisted request? " + "BTC USD ".repeat(8),
        payment_amount_usdc: "0.010000",
        acquisition_status: "SUCCEEDED",
        evidence_status: "ADMITTED",
        evidence_sha: hash,
        decision: "PERMIT",
        result_capability_hash: "must-not-render",
      }],
    };
    const autonomy = {
      global_enabled: false,
      active_policy_count: 2,
      active_run_count: 1,
      today_spend_usdc: "0.012500",
      next_due_at: "2026-09-25T13:00:00+00:00",
    };
    const health = { public_execution: { authority_mode: "BINDING" } };
    const fetch = vi.fn(async (path) => ({
      ok: true,
      json: async () => path.endsWith("public/activity") ? activity : path.endsWith("autonomy/status") ? autonomy : health,
    }));
    let scheduledRefresh;
    const setInterval = vi.fn((callback, delay) => { scheduledRefresh = callback; return 1; });
    dom.window.fetch = fetch;
    dom.window.setInterval = setInterval;
    dom.window.eval(runtimeSource);
    await new Promise((resolve) => setTimeout(resolve, 0));

    const historyRow = document.querySelector("#executionHistoryRows tr");
    const cells = Array.from(historyRow.querySelectorAll("td"));
    expect(cells).toHaveLength(11);
    expect(cells[1].textContent).toBe("M2M");
    expect(cells[2].textContent).toBe("agent-17");
    expect(cells[4].textContent.length).toBeLessThanOrEqual(30);
    expect(cells[4].title).toContain("BTC USD");
    expect(cells[8].textContent).toBe("0xaaaaaa…aaaaaa");
    expect(cells[8].title).toBe(hash);
    expect(cells[9].textContent).toBe("PERMIT");
    expect(cells[10].textContent).toBe("UNKNOWN");
    expect(document.querySelector("#executionHistoryRows").textContent).not.toContain("must-not-render");
    expect(document.querySelector("#runtimeAutonomyGlobal").textContent).toBe("DISABLED");
    expect(document.querySelector("#runtimeAuthorityMode").textContent).toBe("BINDING");
    expect(document.querySelector("#runtimeActivePolicies").textContent).toBe("2");
    expect(document.querySelector("#runtimeG13Policy").textContent).toBe("UNKNOWN");
    expect(document.querySelector("#runtimeActiveRuns").textContent).toBe("1");
    expect(document.querySelector("#runtimeScheduler").textContent).toBe("UNKNOWN");
    expect(document.querySelector("#runtimeTodaySpend").textContent).toBe("0.012500 USDC");
    expect(document.querySelector("#runtimeNextDue").title).toBe(autonomy.next_due_at);
    expect(document.querySelector("#recoveryStateRow").hidden).toBe(false);
    expect(document.querySelector("#recoveryStateValue").textContent).toBe("UNKNOWN");
    const originCount = (origin, column) => Number(document.querySelector(`table.origin tr[data-origin="${origin}"] td:nth-child(${column})`).textContent);
    expect(originCount("autonomous", 2)).toBe(3);
    expect(originCount("autonomous", 3)).toBe(2);
    expect(originCount("manual", 2)).toBe(2);
    expect(originCount("manual", 3)).toBe(1);
    expect(originCount("m2m", 2)).toBe(2);
    expect(originCount("m2m", 3)).toBe(2);
    expect(originCount("user", 2)).toBe(1);
    expect(originCount("user", 3)).toBe(1);
    expect(originCount("total", 2)).toBe(8);
    expect(originCount("total", 3)).toBe(6);
    expect(["autonomous", "manual", "m2m", "user"].reduce((sum, origin) => sum + originCount(origin, 2), 0)).toBe(originCount("total", 2));
    expect(["autonomous", "manual", "m2m", "user"].reduce((sum, origin) => sum + originCount(origin, 3), 0)).toBe(originCount("total", 3));
    expect(setInterval).toHaveBeenCalledWith(expect.any(Function), 12000);

    activity = { ...activity, processed_responses: 9, execution_history: [], recovery_state: "RECOVERY_REQUIRED" };
    await scheduledRefresh();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(document.querySelector(".metric-hero .num").textContent).toBe("9");
    expect(document.querySelector("#executionHistoryRows .empty").textContent).toBe("No persisted execution rows");
    expect(document.querySelector("#recoveryStateValue").textContent).toBe("RECOVERY_REQUIRED");
    expect(fetch).toHaveBeenCalledTimes(6);
    expect(fetch.mock.calls.map(([path]) => path)).toEqual([
      "/api/v1/public/activity", "/api/v1/autonomy/status", "/api/health",
      "/api/v1/public/activity", "/api/v1/autonomy/status", "/api/health",
    ]);
    dom.window.close();
  });
});
