import { ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { ActivityAggregate, Anchor, api, AutonomyPolicy, AutonomyRun, AutonomyStatus, Decision, Erc8183Job, Evaluation, Lineage, Mandate, MandateDetails, OperationalLedger, PublicActivity, Ticket, TicketVerification } from "./api";
import { displayDate, money, shortId, stateTone } from "./format";
import "./styles.css";
import "./refinements.css";
import { TitularCheck } from "./TitularCheck";

type Tab = "MANDATES" | "ERC-8183 JOBS" | "EVIDENCE" | "DECISIONS" | "TICKETS" | "LINEAGE" | "AUTONOMY" | "LOGS" | "ABOUT";
type Snapshot = { mandates: Mandate[]; jobs: Erc8183Job[]; policies: AutonomyPolicy[]; runs: AutonomyRun[]; autonomy: AutonomyStatus | null; activity: PublicActivity | null; apiUp: boolean };
const tabs: Tab[] = ["MANDATES", "ERC-8183 JOBS", "EVIDENCE", "DECISIONS", "TICKETS", "LINEAGE", "AUTONOMY", "LOGS"];
const icons = { mandate: "/Iconos/01-MANDATE.png", acquisition: "/Iconos/02-ACQUISITION.png", evidence: "/Iconos/03-EVIDENCE.png", evaluation: "/Iconos/04-EVALUATION.png", decision: "/Iconos/05-DESICION.png", ticket: "/Iconos/06-TICKET.png", callback: "/Iconos/07-ERC-8183 CALLBACK.png" };
const emptySnapshot: Snapshot = { mandates: [], jobs: [], policies: [], runs: [], autonomy: null, activity: null, apiUp: false };

function Chip({ value }: { value?: string | null }) { const text = value || "UNAVAILABLE"; return <span className={`chip ${stateTone(text)}`}>{text.replace(/_/g, " ")}</span>; }
function Signal({ label, value, detail, mono = false }: { label: string; value: string | number | boolean | null | undefined; detail?: string; mono?: boolean }) { const text = value === null || value === undefined || value === "" ? "NOT EXPOSED" : String(value); return <div className="signal"><span>{label}</span><strong className={mono ? "mono" : ""}>{text}</strong>{detail && <em>{detail}</em>}</div>; }
function Toggle({ label, checked, disabled = false, onChange, note }: { label: string; checked: boolean; disabled?: boolean; onChange?: () => void; note?: string }) { return <div className="toggle-row"><div><span>{label}</span>{note && <small>{note}</small>}</div><button className={`toggle ${checked ? "on" : "off"}`} aria-pressed={checked} disabled={disabled} onClick={onChange} title={disabled ? note || "Read-only" : label}><i /></button></div>; }
function DetailRow({ label, value, mono = false }: { label: string; value?: string | number | boolean | null; mono?: boolean }) { const text = value === null || value === undefined || value === "" ? "—" : String(value); return <div className="detail-row"><span>{label}</span><strong className={mono ? "mono" : ""}>{text}</strong></div>; }
function PanelHeading({ eyebrow, badge }: { eyebrow: string; badge?: string }) { return <div className="panel-heading"><h2>{eyebrow}</h2>{badge && <span>{badge}</span>}</div>; }
function Empty({ label }: { label: string }) { return <p className="empty-note">{label}</p>; }

const MULTI_INTENT_DEMO = [
  ["CRYPTO_PRICE", "What is the current price of Bitcoin in USD?"],
  ["GAS_PRICE", "What are the current Base Sepolia gas conditions?"],
  ["FINANCIAL_DATA", "Provide a current market snapshot for Ethereum."],
  ["TOKEN_HOLDER_COUNT", "What is the current USDC holder count on Base?"],
  ["URL_SCAN", "Check the official Telegraph documentation URL."],
] as const;

function MultiIntentDemo({ onCreated }: { onCreated: (mandateId: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  async function runDemo() {
    if (!window.confirm("Queue one real public multi-intent workflow? It can use up to 0.050000 USDC across five ordered acquisitions and remains subject to the existing rate and settlement controls.")) return;
    setBusy(true); setMessage(null);
    try {
      const mandate = await api.createMandate({
        actor_id: "prama-multi-intent-demo",
        text: "Run the PRAMA-Dynamagh multi-intent demonstration and preserve one lineage across all requested observations.",
        mandate_type: "MULTI_INTENT_DEMO",
        constraints: { demo: true, ordered_fanout: true },
        max_budget_usdc: 0.05,
        acquisitions: MULTI_INTENT_DEMO.map(([requested_intent, query]) => ({ query, requested_intent })),
      });
      setMessage(`Queued ${shortId(mandate.mandate_id)} · follow the live lineage below.`);
      onCreated(mandate.mandate_id);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to queue the demo workflow.");
    } finally { setBusy(false); }
  }
  return <section className="panel multi-intent-demo"><PanelHeading eyebrow="MULTI-INTENT DEMO" badge="UP TO 5 CALLS" /><p className="form-intro">A concrete public workflow that fans out through the normal Mandate → Telegraph → Evidence → Decision → Ticket path.</p><div className="demo-task-list">{MULTI_INTENT_DEMO.map(([intent, query]) => <div className="demo-task" key={intent}><strong>{intent}</strong><span>{query}</span></div>)}</div><button className="primary" type="button" onClick={() => void runDemo()} disabled={busy}>{busy ? "QUEUING…" : "RUN LIVE DEMO"}<span>{busy ? "" : "0.05 USDC max"}</span></button>{message && <p className="form-note demo-message">{message}</p>}</section>;
}

function Pipeline({ details, ercJob }: { details: MandateDetails | null; ercJob: Erc8183Job | null }) {
  const evidence = details?.evidence[0];
  const steps = [
    { key: "mandate", number: "01", title: "Mandate", icon: icons.mandate, exists: Boolean(details?.mandate), status: details?.mandate.status, left: details?.mandate.mandate_id, right: details?.mandate.origin },
    { key: "acquisition", number: "02", title: "Acquisition", icon: icons.acquisition, exists: Boolean(details?.acquisitions.length), status: details?.acquisitions[0]?.status, left: details?.acquisitions[0]?.acquisition_id, right: details?.acquisitions[0]?.intent || "No Telegraph call" },
    { key: "evidence", number: "03", title: "Evidence", icon: icons.evidence, exists: Boolean(evidence), status: evidence?.admissibility, left: evidence?.evidence_id, right: evidence?.provenance_status },
    { key: "evaluation", number: "04", title: "PRAMAgraph Evaluation", icon: icons.evaluation, exists: Boolean(details?.evaluation), status: details?.evaluation?.structural_state, left: details?.evaluation?.evaluation_id, right: details?.evaluation?.evidence_set_hash },
    { key: "decision", number: "05", title: "Decision", icon: icons.decision, exists: Boolean(details?.decision), status: details?.decision?.state, left: details?.decision?.decision_id, right: details?.decision?.policy_version },
    { key: "ticket", number: "06", title: "Ticket", icon: icons.ticket, exists: Boolean(details?.ticket), status: details?.ticket?.anchor_status, left: details?.ticket?.ticket_id, right: details?.ticket?.ticket_hash },
    { key: "callback", number: "07", title: "ERC-8183 Callback", icon: icons.callback, exists: Boolean(ercJob), status: ercJob?.callback_verified ? "CALLBACK VERIFIED" : ercJob?.state, left: ercJob?.erc8183_job_id, right: ercJob?.callback_response_hash },
  ];
  return <section className="pipeline" aria-label="Mandate pipeline">{steps.map((step) => <article className={`pipeline-step ${step.exists ? "complete" : "empty"}`} key={step.key}><div className="step-rail"><b>{step.number}</b><i /></div><img src={step.icon} alt="" /><div className="step-main"><h3>{step.title}</h3><p className="mono">{shortId(step.left)}</p><p>{shortId(step.right, 12)}</p></div><div className="step-state"><Chip value={step.exists ? step.status : "NOT AVAILABLE"} /></div></article>)}</section>;
}

function ProcessOverview() {
  return <section className="panel"><PanelHeading eyebrow="PROCESS CONSOLE" badge="AGENT WORKFLOWS" /><p className="form-intro">Inspect operations submitted by autonomous agents and applications.</p><p className="form-note">Select a persisted mandate to follow its acquisitions, evidence, evaluation, decision and verifiable Ticket.</p></section>;
}

function ControlPanel({ policy, globalEnabled, onRefresh }: { policy: AutonomyPolicy | null; globalEnabled: boolean; onRefresh: () => void }) {
  const [busy, setBusy] = useState(false); async function change(action: () => Promise<unknown>, prompt: string) { if (!window.confirm(prompt)) return; setBusy(true); try { await action(); onRefresh(); } finally { setBusy(false); } }
  return <section className="controls panel"><PanelHeading eyebrow="AUTONOMY CONTROLS" badge={globalEnabled ? "GLOBAL ACTIVE" : "GLOBAL PAUSED"} />{policy ? <><p className="policy-name">{policy.name}</p><Toggle label="Policy enabled" checked={policy.enabled} disabled={busy} note={globalEnabled ? "Functional: changes the persisted policy." : "Global autonomy is disabled; this cannot start runs until the server global switch is enabled."} onChange={() => change(() => api.setPolicyEnabled(policy.policy_id, !policy.enabled), `Change policy ${policy.name} to ${policy.enabled ? "paused" : "active"}?`)} /><Toggle label="Telegraph HTTP" checked={policy.allow_telegraph_http} disabled note="Read-only: acquisition mode is immutable after policy creation." /><Toggle label="ERC-8183" checked={policy.allow_erc8183} disabled note="Read-only: persisted policy capability." /><Toggle label="Anchor" checked={policy.allow_anchor} disabled={busy} note="Functional policy guard; it never creates an anchor by itself." onChange={() => change(() => api.patchPolicy(policy.policy_id, { allow_anchor: !policy.allow_anchor }), "Change the persisted anchor allowance? No transaction will be sent.")} /><Toggle label="Strict verification" checked={policy.strict_verification} disabled={busy} note="Functional policy guard." onChange={() => change(() => api.patchPolicy(policy.policy_id, { strict_verification: !policy.strict_verification }), "Change strict verification for this policy?")} /><Toggle label="Read-only replay" checked={policy.read_only_replay} disabled={busy} note="Functional replay policy control." onChange={() => change(() => api.patchPolicy(policy.policy_id, { read_only_replay: !policy.read_only_replay }), "Change read-only replay for this policy?")} /><div className="budget-grid"><Signal label="CADENCE" value={`${policy.cadence_seconds}s`} /><Signal label="PER RUN" value={money(policy.max_usdc_per_run)} /><Signal label="PER DAY" value={money(policy.max_usdc_per_day)} /><Signal label="RUNS / DAY" value={policy.max_runs_per_day} /></div></> : <Empty label="No persisted autonomy policy is available." />}</section>;
}

function About({ lineage }: { lineage: Lineage | null }) {
  return <section className="about-grid">
    <article className="about-block lead"><span className="eyebrow">ABOUT PRAMA-DYNAMAGH</span><h2>What PRAMA-Dynamagh does</h2><p>PRAMA-Dynamagh is an evidence-bound execution layer for agents. It turns an authorized mandate into ordered Telegraph acquisitions, preserves provenance, evaluates the returned intelligence through PRAMAgraph, and issues a verifiable Decision Ticket before execution continues.</p><p className="about-guard">Before an agent spends money or executes an on-chain action, PRAMA verifies whether the intelligence it received is structurally sound.</p></article>
    <article className="about-block"><h2>How it works</h2><div className="method-line">Authorized work <b>→</b> Cadence <b>→</b> G13 trajectory gate <b>→</b> G12 economic gate <b>→</b> Telegraph / Miner</div><div className="method-line alt">Evidence <b>→</b> PRAMAgraph evaluation <b>→</b> Decision <b>→</b> Ticket <b>→</b> Verification / optional on-chain action</div><p className="about-guard">G13 governs longitudinal trajectory. G12 governs spend. The next action is authorized only when their composition and execution guards permit it.</p></article>
    <article className="about-block"><h2>What is visible in production</h2><ul className="proof-list"><li>Real Telegraph x402 acquisition with Miner, Evidence, Decision and verifiable Ticket lineage.</li><li>Ordered multi-intent fan-out under the existing budget, cadence, idempotency and concurrency controls.</li><li>Separate live records for Manual, M2M and Autonomous activity, with historical totals and observed intents.</li><li>Replayable evidence, decision hashes and Base Sepolia anchoring where requested.</li><li>External failures remain attributable and do not become fabricated success.</li></ul>{lineage && <p className="live-proof">Live lineage: job {lineage.telegraph_job_id || "—"} · callback {lineage.callback_verified ? "VERIFIED" : "UNAVAILABLE"} · Ticket {shortId(lineage.ticket_hash, 12)}</p>}</article>
    <article className="about-block discipline"><h2>Epistemic discipline</h2><p>Acquisition establishes access; provenance establishes origin; evidence establishes an admissible object; structural evaluation tests whether that object can support a decision.</p><p>A Decision Ticket records the chain by which an answer became actionable, so another operator or agent can verify and replay the result.</p><div className="principles"><b>Provenance is not truth.</b><b>Verification is not evaluation.</b><b>A decision must remain reconstructible from its evidence.</b></div></article>
    <article className="about-block why"><h2>Why it matters</h2><p>Agents increasingly act on machine-generated intelligence. PRAMA-Dynamagh adds the accountable layer between information and action: it preserves provenance, tests admissibility, constrains autonomy and leaves a verifiable artifact for every authorized decision.</p><small>Dashboard → Activity → Live Lineage → Decision Ticket</small></article>
  </section>;
}
function AboutBrief() { return <><span className="eyebrow">ABOUT PRAMA-DYNAMAGH</span><h2>What PRAMA-Dynamagh does</h2><p>PRAMA-Dynamagh converts mandates into evidence-bound machine decisions with preserved provenance, structural evaluation and verifiable Decision Tickets.</p><p className="about-guard">Before an agent spends money or executes an on-chain action, PRAMA verifies whether the intelligence it received is structurally sound.</p></>; }

function Table({ headers, rows, empty }: { headers: string[]; rows: Array<Array<string | number | ReactNode>>; empty: string }) { return <div className="table-wrap"><table><thead><tr>{headers.map((header) => <th key={header}>{header}</th>)}</tr></thead><tbody>{rows.length ? rows.map((row, index) => <tr key={index}>{row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>) : <tr><td colSpan={headers.length}><Empty label={empty} /></td></tr>}</tbody></table></div>; }
function DecisionView({ evaluation, decision }: { evaluation: Evaluation | null; decision: Decision | null }) { return <div className="object-grid"><section><PanelHeading eyebrow="STRUCTURAL EVALUATION" /><DetailRow label="Evaluation" value={evaluation?.evaluation_id} mono /><DetailRow label="State" value={evaluation?.structural_state} /><DetailRow label="Evidence set" value={evaluation ? shortId(evaluation.evidence_set_hash, 14) : null} mono /><DetailRow label="Evaluator" value={evaluation?.evaluator_version} /></section><section><PanelHeading eyebrow="DECISION" /><DetailRow label="Decision" value={decision?.decision_id} mono /><DetailRow label="State" value={decision?.state} /><DetailRow label="Policy" value={decision?.policy_version} /><DetailRow label="Reason codes" value={decision?.reason_codes.join(", ")} /></section></div>; }
function TicketView({ ticket, verification, anchor, onShare }: { ticket: Ticket | null; verification: TicketVerification | null; anchor: Anchor | null; onShare: (ticketId: string) => void }) { return <div className="object-grid"><section><PanelHeading eyebrow="DETERMINISTIC TICKET" /><DetailRow label="Ticket" value={ticket?.ticket_id} mono /><DetailRow label="Hash" value={ticket ? shortId(ticket.ticket_hash, 18) : null} mono /><DetailRow label="Schema" value={ticket?.schema_version} /><DetailRow label="Anchor state" value={ticket?.anchor_status} />{ticket && <button className="secondary share-button" onClick={() => onShare(ticket.ticket_id)}>Copy safe share link</button>}</section><section><PanelHeading eyebrow="INDEPENDENT VERIFICATION" /><DetailRow label="Status" value={verification?.status} /><DetailRow label="Payload hash" value={verification?.payload_hash_match === undefined ? null : verification.payload_hash_match ? "MATCH" : "MISMATCH"} /><DetailRow label="Source artifacts" value={verification?.source_artifacts_match === undefined ? null : verification.source_artifacts_match ? "MATCH" : "MISMATCH"} /><DetailRow label="Anchor transaction" value={anchor?.anchor_attempt?.tx_hash ? shortId(anchor.anchor_attempt.tx_hash, 14) : "NOT REQUESTED"} mono /><p className="log-caption">The shared view contains identifiers, statuses and hashes only; it excludes mandate text and provider payloads.</p></section></div>; }
function LineageView({ lineage }: { lineage: Lineage | null }) { if (!lineage) return <Empty label="No persisted ERC-8183 lineage is available." />; const nodes = [["Telegraph output", lineage.telegraph_output_hash], ["Callback commitment", lineage.callback_response_hash], ["Evidence content", lineage.evidence_content_hash], ["Evidence set", lineage.evidence_set_hash], ["Decision", lineage.decision_state], ["Ticket", lineage.ticket_hash], ["Anchor", lineage.anchor_status]]; return <div className="lineage-chain">{nodes.map(([label, value], index) => <div className="lineage-node" key={label}><span>{label}</span><strong className="mono">{shortId(value, 14)}</strong>{index < nodes.length - 1 && <b>↓</b>}</div>)}</div>; }
function ActivityScope({ aggregate, users }: { aggregate?: ActivityAggregate; users?: boolean }) {
  return <>{users && <Signal label="MANUAL USERS" value={aggregate?.real_users} />}<Signal label="WORKFLOWS" value={aggregate ? `${aggregate.workflows_completed}/${aggregate.workflows_started} complete` : null} /><Signal label="MINER RESPONSES" value={aggregate?.processed_responses} /><Signal label="WITH EVIDENCE" value={aggregate?.responses_with_evidence} /><Signal label="UNIQUE MINERS" value={aggregate?.unique_miners_processed.length} /><Signal label="INTENTS" value={aggregate ? Object.keys(aggregate.responses_by_intent).join(", ") || null : null} /></>;
}

function ActivityPanel({ activity }: { activity: PublicActivity | null }) {
  const autonomous = activity?.autonomous;
  const user = activity?.user;
  const manual = activity?.manual ?? (activity ? { ...activity, requester_principals: [], public_spend_usdc: String(activity.public_spend_usdc) } : undefined);
  const m2m = activity?.m2m;
  const scopes = [manual, m2m, user, autonomous].filter((item): item is ActivityAggregate => Boolean(item));
  const totalStarted = scopes.reduce((sum, item) => sum + item.workflows_started, 0);
  const totalCompleted = scopes.reduce((sum, item) => sum + item.workflows_completed, 0);
  const allIntents = Array.from(new Set(scopes.flatMap((item) => Object.keys(item.responses_by_intent))));
  const latest = activity?.latest_miner_response;
  const demand = activity?.demand_origin;
  return <section className="panel activity-panel"><PanelHeading eyebrow="ACTIVITY" badge="REAL RECORDS · LIVE" /><Signal label="ALL HISTORY" value={`${totalCompleted}/${totalStarted} complete`} /><Signal label="MINER RESPONSES PROCESSED" value={demand?.total ?? activity?.processed_responses} /><Signal label="WITH EVIDENCE" value={activity?.responses_with_evidence} /><Signal label="ALL INTENTS" value={allIntents.join(", ") || null} /><div className="activity-scope-heading">DEMAND ORIGIN</div><Signal label="EXTERNAL / USER-DRIVEN" value={demand?.external_user_driven} /><Signal label="  MANUAL" value={demand?.manual} /><Signal label="  M2M · INBOUND" value={demand?.m2m_inbound} /><Signal label="FIXTURE / CANARY" value={demand?.fixture_canary} /><Signal label="UNATTRIBUTED / LEGACY" value={demand?.unattributed_legacy} /><div className="activity-scope-heading">MANUAL REQUESTS</div><ActivityScope aggregate={manual} users /><div className="activity-scope-heading">M2M · INBOUND</div><Signal label="REQUESTS" value={activity?.inbound_m2m_requests} /><Signal label="REQUESTERS" value={activity?.inbound_m2m_requester_principals?.join(", ") || null} /><ActivityScope aggregate={m2m} /><div className="activity-scope-heading">USER / LEGACY USER</div><ActivityScope aggregate={user} /><div className="activity-scope-heading">AUTONOMOUS · INTERNAL</div><ActivityScope aggregate={autonomous} /><div className="activity-scope-heading">LATEST MINER RESPONSE</div><Signal label="MINER" value={latest?.miner_name || latest?.miner_id} /><Signal label="INTENT" value={latest?.intent} /><Signal label="ECONOMIC STATE" value={latest?.economic_state} /><p className="log-caption">Miner responses are completed Telegraph calls with a Miner identity and signal hash. Origin is traced from TelegraphCall → Mandate; explicitly named fixture policies are shown separately from external/user-driven demand.</p></section>;
}

function LedgerRow({ label, value, indent = false }: { label: string; value?: number; indent?: boolean }) {
  return <div className={`ledger-row${indent ? " ledger-row-indent" : ""}`}><span>{indent ? "├─ " : ""}{label}</span><strong>{Number(value || 0).toLocaleString("en-US")}</strong></div>;
}

function OperationalLedgerView({ ledger }: { ledger?: OperationalLedger }) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  if (!ledger) return <p className="ledger-empty">Operational ledger unavailable.</p>;
  const { mandates, autonomous_outcomes: outcomes, telegraph_call_state: calls, authority } = ledger;
  const utcLabel = new Intl.DateTimeFormat("en-GB", {
    timeZone: "UTC",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(now).replace(",", "");
  return <div className="operational-ledger-console" aria-label="Operational ledger">
    <div className="ledger-header"><div className="ledger-title">OPERATIONAL LEDGER</div><strong>PRAMA Dynamagh</strong></div>
    <section><h3>MANDATES</h3><LedgerRow label="Total" value={mandates.total} /><LedgerRow label="Ticketed" value={mandates.ticketed} /><LedgerRow label="Manual" value={mandates.manual} /><LedgerRow label="M2M" value={mandates.m2m} /><LedgerRow label="User / legacy" value={mandates.user} /><LedgerRow label="Autonomous" value={mandates.autonomous} /></section>
    <section><h3>AUTONOMOUS OUTCOMES</h3><LedgerRow label="Telegraph succeeded" value={outcomes.telegraph_succeeded} /><LedgerRow label="Authority restricted" value={outcomes.authority_restricted} /><LedgerRow label="Composition restricted" value={outcomes.composition_restricted} indent /><LedgerRow label="G13 review" value={outcomes.g13_review} indent /><LedgerRow label="External / worker failures" value={outcomes.external_worker_failures} /><LedgerRow label="Running" value={outcomes.running} /></section>
    <section><h3>TELEGRAPH CALL STATE</h3><LedgerRow label="Succeeded" value={calls.succeeded} /><LedgerRow label="Reconciled / no payment" value={calls.reconciled_no_payment} /><LedgerRow label="Payment uncertain" value={calls.payment_uncertain} /><LedgerRow label="Requested" value={calls.requested} /><LedgerRow label="Not executed" value={calls.not_executed} /><LedgerRow label="No TelegraphCall" value={calls.no_telegraph_call} /></section>
    <section><h3>AUTHORITY</h3><LedgerRow label="Next action authorized" value={authority.next_action_authorized} /><LedgerRow label="G13 review" value={authority.g13_review} /><LedgerRow label="G13 throttle" value={authority.g13_throttle} /></section>
    <time className="ledger-utc" dateTime={now.toISOString()}>{utcLabel} UTC</time>
  </div>;
}

function dueLabel(value: string | null | undefined): string | null {
  if (!value) return null;
  const due = new Date(value);
  if (Number.isNaN(due.getTime())) return value;
  return due.getTime() < Date.now() - 60_000 ? `OVERDUE · ${displayDate(value)}` : displayDate(value);
}
function LiveConsole({ snapshot, refreshedAt }: { snapshot: Snapshot; refreshedAt: string | null }) {
  const activity = snapshot.activity;
  const manual = activity?.manual;
  const m2m = activity?.m2m;
  const autonomous = activity?.autonomous;
  const user = activity?.user;
  const autonomousRuns = snapshot.autonomy?.autonomous_runs_total ?? activity?.autonomous_runs ?? 0;
  const totalWorkflows = (manual?.workflows_started ?? 0) + (m2m?.workflows_started ?? 0) + (user?.workflows_started ?? 0) + (autonomous?.workflows_started ?? 0);
  const totalResponses = (manual?.processed_responses ?? 0) + (m2m?.processed_responses ?? 0) + (user?.processed_responses ?? 0) + (autonomous?.processed_responses ?? 0);
  const totalSettled = (Number(manual?.actual_spend_usdc ?? 0) + Number(m2m?.actual_spend_usdc ?? 0) + Number(user?.actual_spend_usdc ?? 0) + Number(autonomous?.actual_spend_usdc ?? 0)).toFixed(6);
  const metric = (label: string, value: string | number | null | undefined) => <Signal label={label} value={value} />;
  return <section className="panel live-console production-activity"><PanelHeading eyebrow="PRODUCTION ACTIVITY" badge={snapshot.apiUp ? "REAL RECORDS · LIVE" : "OFFLINE"} /><div className="production-activity-group"><div className="activity-scope-heading">MANUAL REQUESTS</div>{metric("REQUESTS", manual?.workflows_started)}{metric("MINER RESPONSES", manual?.processed_responses)}{metric("COMPLETED WORKFLOWS", manual ? `${manual.workflows_completed}/${manual.workflows_started}` : null)}</div><div className="production-activity-group"><div className="activity-scope-heading">M2M REQUESTS</div>{metric("REQUESTS", m2m?.workflows_started)}{metric("MINER RESPONSES", m2m?.processed_responses)}{metric("COMPLETED WORKFLOWS", m2m ? `${m2m.workflows_completed}/${m2m.workflows_started}` : null)}</div><div className="production-activity-group"><div className="activity-scope-heading">USER / LEGACY USER</div>{metric("REQUESTS", user?.workflows_started)}{metric("MINER RESPONSES", user?.processed_responses)}</div><div className="production-activity-group"><div className="activity-scope-heading">AUTONOMOUS ACTIVITY</div>{metric("AUTONOMOUS RUNS", autonomousRuns)}{metric("MINER RESPONSES", autonomous?.processed_responses)}{metric("COMPLETED WORKFLOWS", autonomous ? `${autonomous.workflows_completed}/${autonomous.workflows_started}` : null)}{metric("ACTUAL SPEND USDC", autonomous?.actual_spend_usdc)}</div><div className="production-activity-group"><div className="activity-scope-heading">TOTAL PRODUCTION</div>{metric("TOTAL WORKFLOWS", totalWorkflows)}{metric("MINER RESPONSES", totalResponses)}{metric("ACTUAL SPEND USDC", totalSettled)}</div><p className="log-caption">Persisted production records, refreshed every 10 seconds. Miner responses require SUCCEEDED + Miner identity + signal hash; spend is the persisted economic ledger.</p>{refreshedAt && <p className="log-caption">REFRESHED {displayDate(refreshedAt)}</p>}</section>;
}
function LogView({ details, policies }: { details: MandateDetails | null; policies: AutonomyPolicy[] }) { const events = details?.timeline?.events ?? []; return <div className="log-view"><p className="log-caption">Persisted Mandate usage events. No Gateway or private-key logs are exposed to the browser.</p>{events.length ? events.map((event) => <div className="log-row" key={event.event_id}><span>{displayDate(event.created_at)}</span><strong>{event.event_type}</strong><em>{shortId(event.acquisition_id)}</em></div>) : <Empty label="No usage event is available for this Mandate." />}<p className="log-caption">Autonomy policies available: {policies.length}</p></div>; }

type AutonomyRunFilter = "COMPLETED" | "SKIPPED" | "FAILED";

function AutonomyRunsView({ runs, status }: { runs: AutonomyRun[]; status: AutonomyStatus | null }) {
  const [selectedFilter, setSelectedFilter] = useState<AutonomyRunFilter | null>(null);
  const filters: Array<{ key: AutonomyRunFilter; label: string }> = [
    { key: "COMPLETED", label: "COMPLETE" },
    { key: "SKIPPED", label: "SKIPPED" },
    { key: "FAILED", label: "FAILED" },
  ];
  const countFor = (key: AutonomyRunFilter) => key === "COMPLETED"
    ? status?.completed ?? runs.filter((run) => run.state === key).length
    : key === "SKIPPED"
      ? status?.skipped ?? runs.filter((run) => run.state === key).length
      : status?.failed ?? runs.filter((run) => run.state === key).length;
  const visibleRuns = selectedFilter ? runs.filter((run) => run.state === selectedFilter) : [];
  return <div className="autonomy-runs-view">
    <p className="log-caption">Select a persisted run state to open its records. Counts reflect the latest persisted autonomy run window.</p>
    <div className="autonomy-run-filters" role="tablist" aria-label="Autonomy run states">
      {filters.map(({ key, label }) => <button
        key={key}
        type="button"
        role="tab"
        aria-selected={selectedFilter === key}
        className={`autonomy-run-filter${selectedFilter === key ? " active" : ""}`}
        onClick={() => setSelectedFilter(key)}
      >{label}<span>{countFor(key)}</span></button>)}
    </div>
    {selectedFilter ? <Table
      headers={["RUN", "STATE", "MANDATE", "PLANNED", "ACTUAL", "REASON", "FINISHED"]}
      rows={visibleRuns.map((run) => [
        shortId(run.run_id),
        <Chip value={run.state === "COMPLETED" ? "COMPLETE" : run.state} />,
        shortId(run.mandate_id),
        money(run.planned_cost_usdc),
        money(run.actual_cost_usdc),
        run.failure_code || run.skip_reason || "—",
        displayDate(run.finished_at),
      ])}
      empty={`No ${labelForRunState(selectedFilter).toLowerCase()} autonomy runs are available in the current persisted window.`}
    /> : <p className="autonomy-run-placeholder">Choose COMPLETE, SKIPPED, or FAILED to view those persisted runs.</p>}
  </div>;
}

function labelForRunState(state: AutonomyRunFilter): string {
  return state === "COMPLETED" ? "COMPLETE" : state;
}

function TabContent({ tab, details, jobs, policies, runs, autonomy, lineage, onShare }: { tab: Tab; details: MandateDetails | null; jobs: Erc8183Job[]; policies: AutonomyPolicy[]; runs: AutonomyRun[]; autonomy: AutonomyStatus | null; lineage: Lineage | null; onShare: (ticketId: string) => void }) {
  const evidence = details?.evidence ?? []; const ticket = details?.ticket;
  if (tab === "ABOUT") return <About lineage={lineage} />;
  if (tab === "MANDATES") return <Table headers={["ID", "INSTRUCTION", "ORIGIN", "STATUS", "BUDGET", "UPDATED"]} rows={details ? [[shortId(details.mandate.mandate_id), details.mandate.text, details.mandate.origin, <Chip value={details.mandate.status} />, money(details.mandate.max_budget_usdc), displayDate(details.mandate.updated_at)]] : []} empty="Select a persisted Mandate to inspect it." />;
  if (tab === "ERC-8183 JOBS") return <Table headers={["JOB", "INTENT", "STATE", "CALLBACK", "BUDGET", "TERMINAL TX"]} rows={jobs.map((job) => [shortId(job.erc8183_job_id), job.intent_name, <Chip value={job.state} />, job.callback_verified ? "VERIFIED" : "NOT VERIFIED", money(job.budget_usdc), shortId(job.terminal_tx_hash, 10)])} empty="No persisted ERC-8183 job is available." />;
  if (tab === "EVIDENCE") return <Table headers={["EVIDENCE", "PROVENANCE", "ADMISSIBILITY", "INTENT", "CONTENT HASH"]} rows={evidence.map((item) => [shortId(item.evidence_id), <Chip value={item.provenance_status} />, <Chip value={item.admissibility} />, item.source_intent || "—", shortId(item.content_hash, 12)])} empty="No Evidence has been persisted for this Mandate." />;
  if (tab === "DECISIONS") return <DecisionView evaluation={details?.evaluation || null} decision={details?.decision || null} />;
  if (tab === "TICKETS") return <TicketView ticket={ticket || null} verification={details?.verification || null} anchor={details?.anchor || null} onShare={onShare} />;
  if (tab === "LINEAGE") return <LineageView lineage={lineage} />;
  if (tab === "AUTONOMY") return <AutonomyRunsView runs={runs} status={autonomy} />;
  return <LogView details={details} policies={policies} />;
}

function App() {
  const [snapshot, setSnapshot] = useState<Snapshot>(emptySnapshot); const [selectedId, setSelectedId] = useState<string | null>(null); const [details, setDetails] = useState<MandateDetails | null>(null); const [lineage, setLineage] = useState<Lineage | null>(null); const [tab, setTab] = useState<Tab>("MANDATES"); const [error, setError] = useState<string | null>(null); const [shareMessage, setShareMessage] = useState<string | null>(null); const [loading, setLoading] = useState(true); const [refreshedAt, setRefreshedAt] = useState<string | null>(null); const [topAboutOpen, setTopAboutOpen] = useState(false); const [bottomAboutPosition, setBottomAboutPosition] = useState<{ top: number; left: number; width: number; maxHeight: number } | null>(null); const [ledgerPosition, setLedgerPosition] = useState<{ top: number; left: number; width: number; maxHeight: number } | null>(null); const centerRef = useRef<HTMLElement>(null); const bottomAboutButtonRef = useRef<HTMLButtonElement>(null); const ledgerButtonRef = useRef<HTMLButtonElement>(null); const toggleBottomAbout = () => { if (bottomAboutPosition) { setBottomAboutPosition(null); return; } const button = bottomAboutButtonRef.current; const center = centerRef.current; if (!button || !center) return; const buttonBox = button.getBoundingClientRect(); const centerBox = center.getBoundingClientRect(); const margin = 14; const width = Math.min(centerBox.width, window.innerWidth - margin * 2); const left = Math.min(Math.max(centerBox.left, margin), window.innerWidth - width - margin); const maxHeight = Math.max(170, window.innerHeight - margin * 2); const top = Math.min(Math.max(margin, buttonBox.top - maxHeight - margin), window.innerHeight - maxHeight - margin); setBottomAboutPosition({ top, left, width, maxHeight }); }; const toggleLedger = () => { if (ledgerPosition) { setLedgerPosition(null); return; } const button = ledgerButtonRef.current; const center = centerRef.current; if (!button || !center) return; const buttonBox = button.getBoundingClientRect(); const centerBox = center.getBoundingClientRect(); const margin = 14; const width = Math.min(560, window.innerWidth - margin * 2, Math.max(360, centerBox.width - 24)); const left = Math.min(Math.max(centerBox.left + (centerBox.width - width) / 2, margin), window.innerWidth - width - margin); const maxHeight = Math.min(700, Math.max(260, window.innerHeight - margin * 2)); const top = Math.min(Math.max(margin, buttonBox.top - maxHeight - margin), window.innerHeight - maxHeight - margin); setLedgerPosition({ top, left, width, maxHeight }); };
  async function refresh(preferredId?: string) { setLoading(true); setError(null); try { const [health, mandates, jobs, policies, runs, autonomy, activity] = await Promise.all([api.health(), api.mandates(), api.jobs(), api.policies(), api.runs(), api.autonomy(), api.activity()]); setSnapshot({ mandates, jobs, policies, runs, autonomy, activity, apiUp: health.status === "ok" }); setRefreshedAt(new Date().toISOString()); const next = preferredId || selectedId || mandates[0]?.mandate_id || null; if (next) { const [loadedDetails, loadedLineage] = await Promise.all([api.mandateDetails(next), jobs[0] ? api.lineage(jobs[0].erc8183_job_id) : Promise.resolve(null)]); setSelectedId(next); setDetails(loadedDetails); setLineage(loadedLineage); } else { setDetails(null); setLineage(null); } } catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to load the operator surfaces."); } finally { setLoading(false); } }
  async function refreshActivity() { try { const [activity, autonomy] = await Promise.all([api.activity(), api.autonomy()]); setSnapshot((current) => ({ ...current, activity, autonomy })); setRefreshedAt(new Date().toISOString()); } catch { /* Keep the last known real-record snapshot during a transient poll failure. */ } }
  useEffect(() => { void refresh(); }, []);
  useEffect(() => { const timer = window.setInterval(() => void refresh(selectedId || undefined), 30000); return () => window.clearInterval(timer); }, [selectedId]);
  useEffect(() => { const timer = window.setInterval(() => void refreshActivity(), 10000); return () => window.clearInterval(timer); }, []);
  async function selectMandate(mandateId: string) { setSelectedId(mandateId); setLoading(true); setError(null); try { setDetails(await api.mandateDetails(mandateId)); } catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to load mandate."); } finally { setLoading(false); } }
  const activePolicy = useMemo(() => snapshot.policies.find((policy) => policy.enabled) || snapshot.policies.find((policy) => policy.name.includes("Live")) || snapshot.policies[0] || null, [snapshot.policies]);
  // ERC-8183 jobs are valid persisted chain records even when they predate or
  // are not attached to the currently selected mandate.
  const selectedJob = useMemo(() => snapshot.jobs.find((job) => job.mandate_id === selectedId) || snapshot.jobs[0] || null, [snapshot.jobs, selectedId]);
  async function shareTicket(ticketId: string) { const url = `${window.location.origin}/api/v1/tickets/${ticketId}/share`; try { await navigator.clipboard.writeText(url); setShareMessage("Safe Ticket link copied."); } catch { setShareMessage(url); } window.setTimeout(() => setShareMessage(null), 5000); }
  function handleDemoCreated(mandateId: string) { setTab("MANDATES"); void refresh(mandateId); }
  return <main className="app-shell"><header className="topbar"><div className="brand"><img src="/LOGOS identidad/PRAMA-Dynamagh logo.png" alt="PRAMA-Dynamagh" /><span>Structural Epistemic Layer</span><button type="button" className={`about-trigger about-trigger-logo ${topAboutOpen ? "active" : ""}`} aria-pressed={topAboutOpen} onClick={() => setTopAboutOpen((open) => !open)}>About<span>PRAMA-Dynamagh</span></button></div><div className="service-strip"><Chip value={snapshot.apiUp ? "API UP" : "API UNAVAILABLE"} /><span className="service-muted">Worker · internal</span><span className="service-muted">Gateway · protected</span><span>Chain · {selectedJob?.chain_id || "NOT EXPOSED"}</span><span>Mode · {snapshot.autonomy?.global_enabled ? "AUTONOMOUS" : "MANUAL"}</span></div></header>{error && <div className="alert">{error}<button onClick={() => void refresh(selectedId || undefined)}>Retry</button></div>}{shareMessage && <div className="alert share-alert">{shareMessage}</div>}<div className="workspace"><aside className="sidebar"><ProcessOverview /><MultiIntentDemo onCreated={handleDemoCreated} /><ControlPanel policy={activePolicy} globalEnabled={Boolean(snapshot.autonomy?.global_enabled)} onRefresh={() => void refresh(selectedId || undefined)} /><section className="panel mandate-selector"><PanelHeading eyebrow="PERSISTED MANDATES" badge={`${snapshot.mandates.length}`} /><select value={selectedId || ""} onChange={(event) => void selectMandate(event.target.value)}>{snapshot.mandates.map((mandate) => <option key={mandate.mandate_id} value={mandate.mandate_id}>{shortId(mandate.mandate_id)} · {mandate.status} · {mandate.origin}</option>)}</select><button className="secondary" onClick={() => void refresh(selectedId || undefined)} disabled={loading}>Refresh read surfaces</button></section><button type="button" ref={ledgerButtonRef} className={`about-trigger about-trigger-panel ledger-trigger ${ledgerPosition ? "active" : ""}`} aria-pressed={Boolean(ledgerPosition)} onClick={toggleLedger}>Operational Ledger<span>Live production records</span></button></aside><section className="center" ref={centerRef}>{topAboutOpen ? <section className="about-stage"><button type="button" className="about-close" aria-label="Close About" onClick={() => setTopAboutOpen(false)}>×</button><About lineage={lineage} /></section> : <><Pipeline details={details} ercJob={selectedJob} /><nav className="tabs" aria-label="Operator views">{tabs.map((item) => <button key={item} className={tab === item ? "active" : ""} onClick={() => setTab(item)}>{item === "ABOUT" ? "ABOUT PRAMA-DYNAMAGH" : item}</button>)}</nav><section className="tab-panel">{loading ? <div className="loading">Loading persisted system state…</div> : <TabContent tab={tab} details={details} jobs={snapshot.jobs} policies={snapshot.policies} runs={snapshot.runs} autonomy={snapshot.autonomy} lineage={lineage} onShare={(ticketId) => void shareTicket(ticketId)} />}</section></>}</section><aside className="telemetry"><LiveConsole snapshot={snapshot} refreshedAt={refreshedAt} /><section className="panel"><PanelHeading eyebrow="RUNTIME" badge="READ ONLY" /><Signal label="AUTONOMY GLOBAL" value={snapshot.autonomy?.global_enabled ? "ENABLED" : "DISABLED"} /><Signal label="ACTIVE POLICIES" value={snapshot.autonomy?.active_policy_count} /><Signal label="ACTIVE RUNS" value={snapshot.autonomy?.active_run_count} /><Signal label="TODAY SPEND" value={money(snapshot.autonomy?.today_spend_usdc)} /><Signal label="NEXT DUE" value={dueLabel(snapshot.autonomy?.next_due_at)} /></section><ActivityPanel activity={snapshot.activity} /><section className="panel"><PanelHeading eyebrow="CHAIN" badge="PERSISTED" /><Signal label="NETWORK" value={selectedJob?.chain_id ? `Base Sepolia (${selectedJob.chain_id})` : null} /><Signal label="ERC-8183 CREATE TX" value={shortId(selectedJob?.create_tx_hash, 10)} mono /><Signal label="ERC-8183 TERMINAL TX" value={shortId(selectedJob?.terminal_tx_hash, 10)} mono /><Signal label="TICKET ANCHOR" value={details?.anchor?.anchor_status || details?.ticket?.anchor_status} /><Signal label="TICKET TX" value={shortId(details?.anchor?.anchor_attempt?.tx_hash, 10)} mono /></section><section className="panel"><PanelHeading eyebrow="TELEGRAPH" badge="PERSISTED" /><Signal label="INTENT" value={details?.acquisitions[0]?.intent || selectedJob?.intent_name} /><Signal label="MINER" value={details?.acquisitions[0]?.miner_name || details?.acquisitions[0]?.miner_id || "ERC-8183"} /><Signal label="SIGNAL" value={shortId(details?.acquisitions[0]?.signal_hash, 10)} /><Signal label="COST" value={money(details?.acquisitions[0]?.cost_usd || selectedJob?.budget_usdc)} /><Signal label="DURATION" value={details?.acquisitions[0]?.duration_ms ? `${details.acquisitions[0].duration_ms} ms` : null} /></section><section className="panel"><PanelHeading eyebrow="CURRENT OBJECT" /><Signal label="MANDATE" value={shortId(details?.mandate.mandate_id)} /><Signal label="ORIGIN" value={details?.mandate.origin} /><Signal label="STATUS" value={details?.mandate.status} /><Signal label="DECISION" value={details?.decision?.state} /><Signal label="TICKET" value={shortId(details?.ticket?.ticket_hash, 10)} /></section><button type="button" ref={bottomAboutButtonRef} className={`about-trigger about-trigger-panel ${bottomAboutPosition ? "active" : ""}`} aria-pressed={Boolean(bottomAboutPosition)} onClick={toggleBottomAbout}>About<span>PRAMA-Dynamagh</span></button></aside></div>{bottomAboutPosition && <section className="about-bottom-stage" style={{ top: `${bottomAboutPosition.top}px`, left: `${bottomAboutPosition.left}px`, width: `${bottomAboutPosition.width}px`, maxHeight: `${bottomAboutPosition.maxHeight}px` }}><About lineage={lineage} /></section>}{ledgerPosition && <section className="operational-ledger-stage" style={{ top: `${ledgerPosition.top}px`, left: `${ledgerPosition.left}px`, width: `${ledgerPosition.width}px`, maxHeight: `${ledgerPosition.maxHeight}px` }}><button type="button" className="about-close" aria-label="Close Operational Ledger" onClick={() => setLedgerPosition(null)}>×</button><OperationalLedgerView ledger={snapshot.activity?.operational_ledger} /></section>}<footer><img src="/LOGOS identidad/Aptadynamik Logo.png" alt="Aptadynamik" /> <span>Cybernetics</span><span>G11 local interface · read surfaces never spend</span></footer></main>;
}

createRoot(document.getElementById("root")!).render(window.location.pathname === "/titular-check" || window.location.pathname.startsWith("/titular-check/") ? <TitularCheck /> : <App />);
