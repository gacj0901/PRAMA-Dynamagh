(() => {
  const money = (value) => `${Number(value || 0).toFixed(6)} USDC`;
  const setText = (selector, value) => {
    const node = document.querySelector(selector);
    if (node) node.textContent = value == null || value === "" ? "—" : String(value);
  };
  const setValue = (row, value) => {
    const node = row?.querySelector("span:last-child");
    if (node) node.textContent = value == null || value === "" ? "—" : String(value);
  };
  const aggregateRows = () => Array.from(document.querySelectorAll("table.origin tr"));

  function render(data) {
    const autonomous = data.autonomous || {};
    const manual = data.manual || {};
    const m2m = data.m2m || {};
    const user = data.user || {};
    const ledger = data.operational_ledger || {};
    const demand = data.demand_origin || {};
    const latest = data.latest_miner_response || autonomous.latest_miner_response || manual.latest_miner_response;

    setText(".metric-hero .num", data.processed_responses ?? 0);
    setText(".metric-hero .cap", `RESPONSES PROCESSED · ${data.responses_with_evidence ?? 0} WITH EVIDENCE`);
    const rows = aggregateRows();
    const originValues = [
      [autonomous.processed_responses, autonomous.responses_with_evidence],
      [manual.processed_responses, manual.responses_with_evidence],
      [m2m.processed_responses, m2m.responses_with_evidence],
      [user.processed_responses, user.responses_with_evidence],
      [data.processed_responses, data.responses_with_evidence],
    ];
    rows.slice(1, 6).forEach((row, index) => {
      const values = originValues[index] || [0, 0];
      if (row.children[1]) row.children[1].textContent = String(values[0] ?? 0);
      if (row.children[2]) row.children[2].textContent = String(values[1] ?? 0);
    });

    const intentList = document.querySelector(".intent-list");
    if (intentList) {
      const entries = Object.entries(data.responses_by_intent || {}).sort((a, b) => b[1] - a[1]);
      intentList.innerHTML = entries.length
        ? entries.map(([intent, count]) => `<div class="intent-row"><span>${intent}</span><span>${count}</span></div>`).join("")
        : '<div class="intent-row"><span>—</span><span>0</span></div>';
    }

    if (latest) {
      const values = document.querySelectorAll(".latest-grid .trow span:last-child");
      [latest.intent, latest.miner_name || latest.miner_id, latest.signal_hash ? `${latest.signal_hash.slice(0, 12)}…` : null, money(latest.cost_usdc), latest.duration_ms ? `${latest.duration_ms} ms` : null, latest.with_evidence ? "ADMITTED" : "NOT AVAILABLE"].forEach((value, index) => {
        if (values[index]) values[index].textContent = value || "—";
      });
    }

    const runtimeRows = document.querySelectorAll(".runtime-inline .runtime-grid .trow");
    [
      data.autonomous_runs != null ? "ENABLED" : "—",
      data.scope?.included_origins ? "BINDING" : "—",
      ledger.mandates?.autonomous ?? autonomous.workflows_started ?? 0,
      "g13-d-structural-autonomy-v0.4",
      0,
      "ACTIVE",
      money(data.actual_spend_usdc),
      "—",
    ].forEach((value, index) => setValue(runtimeRows[index], value));

    setText("#pipelineMandate", latest?.mandate_id ? `live mandate ${latest.mandate_id.slice(0, 8)}…` : "live production read model");
    setText("#publicTotal", `${ledger.mandates?.ticketed ?? 0}/${ledger.mandates?.total ?? 0} ticketed`);
    setText("#publicResponses", data.processed_responses ?? 0);
    setText("#publicEvidence", data.responses_with_evidence ?? 0);
    setText("#publicExternal", demand.external_user_driven ?? 0);
    setText("#publicManual", demand.manual ?? 0);
    setText("#publicM2M", demand.m2m_inbound ?? 0);
    setText("#publicFixture", demand.fixture_canary ?? 0);
    setText("#publicLegacy", demand.unattributed_legacy ?? 0);
    setText("#publicSpend", money(data.actual_spend_usdc));
  }

  async function refresh() {
    const apiPill = document.querySelector(".status .pill");
    try {
      const response = await fetch("/api/v1/public/activity", { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      render(await response.json());
      if (apiPill) { apiPill.textContent = "API UP"; apiPill.classList.add("on"); }
    } catch {
      if (apiPill) { apiPill.textContent = "API UNAVAILABLE"; apiPill.classList.remove("on"); }
    }
  }

  refresh();
  window.setInterval(refresh, 10000);
})();
