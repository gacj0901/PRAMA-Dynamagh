(() => {
  const REFRESH_INTERVAL_MS = 12000;
  const QUERY_PREVIEW_LIMIT = 30;
  const money = (value) => `${Number(value || 0).toFixed(6)} USDC`;
  const setText = (selector, value) => {
    const node = document.querySelector(selector);
    if (node) node.textContent = value == null || value === "" ? "—" : String(value);
  };
  function historyCell(value, { title, className } = {}) {
    const cell = document.createElement("td");
    cell.textContent = value == null || value === "" ? "—" : String(value);
    if (title) cell.title = String(title);
    if (className) cell.className = className;
    return cell;
  }

  function formatTime(value) {
    if (!value) return "—";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "—" : date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false });
  }

  function renderHistory(history) {
    const body = document.querySelector("#executionHistoryRows");
    if (!body) return;
    body.replaceChildren();
    const rows = Array.isArray(history) ? history : [];
    if (!rows.length) {
      const row = document.createElement("tr");
      const empty = historyCell("No persisted execution rows", { className: "empty" });
      empty.colSpan = 11;
      row.append(empty);
      body.append(row);
      return;
    }

    rows.forEach((item) => {
      const row = document.createElement("tr");
      const query = item.query == null ? "" : String(item.query);
      const queryPreview = query.length > QUERY_PREVIEW_LIMIT
        ? `${query.slice(0, QUERY_PREVIEW_LIMIT - 1)}…`
        : query;
      const sha = item.evidence_sha == null ? "" : String(item.evidence_sha);
      const shortSha = sha.length > 14 ? `${sha.slice(0, 8)}…${sha.slice(-6)}` : sha;
      const rawPayment = item.payment_amount_usdc;
      const payment = rawPayment == null || rawPayment === ""
        ? "—"
        : Number.isFinite(Number(rawPayment)) ? Number(rawPayment).toFixed(2) : String(rawPayment);
      [
        historyCell(formatTime(item.time), { title: item.time }),
        historyCell(item.origin, { title: item.origin }),
        historyCell(item.client, { title: item.client }),
        historyCell(item.intent, { title: item.intent }),
        historyCell(queryPreview, { title: query }),
        historyCell(payment, { title: rawPayment == null ? undefined : `${rawPayment} USDC` }),
        historyCell(item.acquisition_status, { title: item.acquisition_status }),
        historyCell(item.evidence_status, { title: item.evidence_status }),
        historyCell(shortSha, { title: sha || undefined, className: "sha" }),
        historyCell(item.decision, { title: item.decision }),
        historyCell(item.delivery_status || "UNKNOWN", { title: item.delivery_status || "UNKNOWN" }),
      ].forEach((cell) => row.append(cell));
      body.append(row);
    });
  }

  function renderRuntime(activity, autonomy, health) {
    const active = (value) => typeof value === "boolean" ? (value ? "ENABLED" : "DISABLED") : "—";
    const setDue = (value) => {
      const node = document.querySelector("#runtimeNextDue");
      if (!node) return;
      if (!value) { node.textContent = "—"; node.removeAttribute("title"); return; }
      const date = new Date(value);
      node.textContent = Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
      node.title = String(value);
    };
    setText("#runtimeAutonomyGlobal", active(autonomy?.global_enabled));
    setText("#runtimeAuthorityMode", health?.public_execution?.authority_mode || "—");
    setText("#runtimeActivePolicies", autonomy?.active_policy_count);
    setText("#runtimeG13Policy", autonomy?.g13_policy || activity?.g13_policy || "UNKNOWN");
    setText("#runtimeActiveRuns", autonomy?.active_run_count);
    setText("#runtimeScheduler", autonomy?.scheduler_state || activity?.scheduler_state || "UNKNOWN");
    setText("#runtimeTodaySpend", autonomy?.today_spend_usdc == null ? "—" : money(autonomy.today_spend_usdc));
    setDue(autonomy?.next_due_at);
    const recovery = autonomy?.recovery_state || activity?.recovery_state;
    const recoveryRow = document.querySelector("#recoveryStateRow");
    if (recoveryRow) recoveryRow.hidden = false;
    setText("#recoveryStateValue", recovery || "UNKNOWN");
  }

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
    const originValues = {
      autonomous: [autonomous.processed_responses, autonomous.responses_with_evidence],
      manual: [manual.processed_responses, manual.responses_with_evidence],
      m2m: [m2m.processed_responses, m2m.responses_with_evidence],
      user: [user.processed_responses, user.responses_with_evidence],
      total: [data.processed_responses, data.responses_with_evidence],
    };
    document.querySelectorAll("table.origin tr[data-origin]").forEach((row) => {
      const values = originValues[row.dataset.origin] || [0, 0];
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
    renderHistory(data.execution_history);
  }

  async function getJson(path) {
    const response = await window.fetch(path, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }

  let refreshInFlight = false;
  async function refresh() {
    const apiPill = document.querySelector(".status .pill");
    if (refreshInFlight) return;
    refreshInFlight = true;
    try {
      const [activityResult, autonomyResult, healthResult] = await Promise.allSettled([
        getJson("/api/v1/public/activity"),
        getJson("/api/v1/autonomy/status"),
        getJson("/api/health"),
      ]);
      if (activityResult.status !== "fulfilled") throw activityResult.reason;
      const autonomy = autonomyResult.status === "fulfilled" ? autonomyResult.value : null;
      const health = healthResult.status === "fulfilled" ? healthResult.value : null;
      render(activityResult.value);
      renderRuntime(activityResult.value, autonomy, health);
      if (apiPill) { apiPill.textContent = "API UP"; apiPill.classList.add("on"); }
    } catch {
      if (apiPill) { apiPill.textContent = "API UNAVAILABLE"; apiPill.classList.remove("on"); }
    } finally {
      refreshInFlight = false;
    }
  }

  refresh();
  window.setInterval(refresh, REFRESH_INTERVAL_MS);
})();
