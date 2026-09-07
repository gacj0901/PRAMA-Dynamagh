import { useCallback, useEffect, useRef, useState } from "react";
import { TurnstileGate } from "./TurnstileGate";
import "./titular-check.css";

export type Receipt = {
  issuer: string; response_hash: string; created_at: string | null;
  workflow: { origin: string; status: string; mandate_type: string };
  acquisitions: { status: string; intent: string | null; requested_intent: string | null; miner: string | null; cost_usdc: string; duration_ms: number | null }[];
  cost_usdc: string;
  evidence: { evidence_id: string; admissibility: string; provenance_status: string; source_intent: string | null; content_hash: string }[];
  evaluation: { structural_state: string; limitations: string[]; contradictions: string[] } | null;
  decision: { state: string; reason_codes: string[] } | null;
  limitations: string[];
  ticket: { schema_version: string; anchor_status: string };
  verification: { status: string; payload_hash_match: boolean | null; source_artifacts_match: boolean | null; reconstructed_hash: string | null };
  replay: { status: string };
};

export function receiptHash(path: string): string | null {
  return /^\/titular-check\/([0-9a-f]{64})-prama-dynamagh$/.exec(path)?.[1] ?? null;
}

function normalizeHash(value: string | null): string | null {
  return value && /^(0x)?[0-9a-fA-F]{64}$/.test(value) ? value.replace(/^0x/, "").toLowerCase() : null;
}

export function verificationLabel(receipt: Receipt, hash: string): string {
  const v = receipt.verification;
  if (normalizeHash(receipt.response_hash) !== hash || v.status === "INVALID" ||
      v.payload_hash_match === false || v.source_artifacts_match === false ||
      receipt.replay.status === "INVALID" ||
      (v.reconstructed_hash !== null && normalizeHash(v.reconstructed_hash) !== hash)) return "VERIFICATION FAILED";
  if (v.status === "VALID" && v.payload_hash_match === true && v.source_artifacts_match === true &&
      normalizeHash(v.reconstructed_hash) === hash && receipt.replay.status === "VALID") return "VERIFIED";
  return "VERIFICATION UNAVAILABLE";
}

type LoadState = { kind: "READY"; receipt: Receipt } | { kind: "INVALID RECEIPT" | "RECEIPT NOT FOUND" | "VERIFICATION UNAVAILABLE" | "VERIFYING" | "HUMAN PRESENCE REQUIRED" | "HUMAN PRESENCE UNAVAILABLE" };

export async function fetchReceipt(path: string, accessToken: string): Promise<LoadState> {
  if (!receiptHash(path)) return { kind: "INVALID RECEIPT" };
  if (!accessToken) return { kind: "HUMAN PRESENCE REQUIRED" };
  try {
    const response = await fetch(`/api/v1${path}`, { method: "GET", cache: "no-store", credentials: "omit", headers: { Authorization: `Bearer ${accessToken}` } });
    if (response.status === 403) return { kind: "HUMAN PRESENCE REQUIRED" };
    if (response.status === 404) return { kind: "RECEIPT NOT FOUND" };
    if (!response.ok) return { kind: "VERIFICATION UNAVAILABLE" };
    const receipt: Receipt = await response.json();
    if (!receipt.verification || !receipt.replay || !Array.isArray(receipt.evidence) || !Array.isArray(receipt.acquisitions) || !receipt.ticket || !receipt.workflow) return { kind: "VERIFICATION UNAVAILABLE" };
    return { kind: "READY", receipt };
  } catch { return { kind: "VERIFICATION UNAVAILABLE" }; }
}

function Line({ label, value }: { label: string; value: string | number | null | undefined }) {
  return <div className="tc-line"><dt>{label}</dt><dd>{value ?? "NOT AVAILABLE"}</dd></div>;
}
const match = (value: boolean | null) => value === true ? "MATCH" : value === false ? "MISMATCH" : "UNAVAILABLE";
const codes = (items: string[] | undefined) => items ? (items.join(" · ") || "NONE") : "NOT AVAILABLE";

export function ReceiptBody({ receipt, hash, label }: { receipt: Receipt; hash: string; label: string }) {
  const [copyState, setCopyState] = useState("COPY HASH");
  async function copyHash() {
    try { await navigator.clipboard.writeText(receipt.response_hash); setCopyState("COPIED"); }
    catch { setCopyState("SELECT HASH TO COPY"); }
  }
  return <>
    <section className="tc-outcome" aria-label="Verification and decision">
      <p className={label === "VERIFIED" ? "tc-verified" : "tc-alert"}>{label}</p>
      <h2 className="tc-decision">{receipt.decision?.state ?? "DECISION UNAVAILABLE"}</h2>
      <span className="tc-label">TELEGRAPH COST</span><p className="tc-cost">{receipt.cost_usdc} <small>USDC</small></p>
    </section>
    <section className="tc-identity"><h2>RESPONSE HASH</h2><code className="tc-hash" title={receipt.response_hash}>{receipt.response_hash}</code><button type="button" className="tc-copy" onClick={() => void copyHash()}>{copyState}</button><dl><Line label="Issuer" value="PRAMA-Dynamagh" /><Line label="Issued" value={receipt.created_at} /><Line label="Origin" value={receipt.workflow.origin} /><Line label="Workflow" value={receipt.workflow.mandate_type} /><Line label="Agent" value={null} /></dl></section>
    <section><h2>INTELLIGENCE / {String(receipt.acquisitions.length).padStart(2, "0")}</h2>{receipt.acquisitions.length ? receipt.acquisitions.map((item, index) => <dl className="tc-record" key={index}><Line label="Acquisition" value={`${index + 1} / ${item.status}`} /><Line label="Intent" value={item.intent ?? item.requested_intent} /><Line label="Miner" value={item.miner} /><Line label="Cost" value={`${item.cost_usdc} USDC`} /><Line label="Duration" value={item.duration_ms === null ? null : `${item.duration_ms} ms`} /></dl>) : <p>NO PUBLISHED ACQUISITIONS</p>}</section>
    <section><h2>EVIDENCE / {String(receipt.evidence.length).padStart(2, "0")}</h2>{receipt.evidence.length ? receipt.evidence.map(item => <dl className="tc-record" key={item.evidence_id}><Line label="Evidence" value={item.evidence_id} /><Line label="Admissibility" value={item.admissibility} /><Line label="Provenance" value={item.provenance_status} /><Line label="Source intent" value={item.source_intent} /><Line label="Content hash" value={item.content_hash} /></dl>) : <p>NO PUBLISHED EVIDENCE</p>}</section>
    <section><h2>STRUCTURAL EVALUATION</h2><dl><Line label="State" value={receipt.evaluation?.structural_state} /><Line label="Limitations" value={codes(receipt.limitations)} /><Line label="Contradictions" value={codes(receipt.evaluation?.contradictions)} /><Line label="Decision reasons" value={codes(receipt.decision?.reason_codes)} /><Line label="Schema" value={receipt.ticket.schema_version} /><Line label="Anchor" value={receipt.ticket.anchor_status} /><Line label="Payload" value={match(receipt.verification.payload_hash_match)} /><Line label="Sources" value={match(receipt.verification.source_artifacts_match)} /><Line label="Reconstruction" value={receipt.verification.reconstructed_hash === null ? "UNAVAILABLE" : normalizeHash(receipt.verification.reconstructed_hash) === hash ? "MATCH" : "MISMATCH"} /><Line label="Replay" value={receipt.replay.status} /></dl></section>
  </>;
}

export function TitularCheck({ path = window.location.pathname }: { path?: string }) {
  const [state, setState] = useState<LoadState>({ kind: receiptHash(path) ? "HUMAN PRESENCE REQUIRED" : "INVALID RECEIPT" });
  const [siteKey, setSiteKey] = useState("");
  const [accessToken, setAccessToken] = useState("");
  const [ack, setAck] = useState("");
  const generation = useRef(0);
  useEffect(() => {
    let active = true;
    generation.current += 1;
    setAccessToken(""); setAck(""); setSiteKey("");
    setState({ kind: receiptHash(path) ? "HUMAN PRESENCE REQUIRED" : "INVALID RECEIPT" });
    if (receiptHash(path)) void fetch("/api/v1/titular-check/config", { method: "GET", cache: "no-store", credentials: "omit" })
      .then(async response => { if (!response.ok) throw new Error(); return response.json(); })
      .then(config => { if (active) { if (config.site_key) setSiteKey(config.site_key); else setState({ kind: "HUMAN PRESENCE UNAVAILABLE" }); } })
      .catch(() => { if (active) setState({ kind: "HUMAN PRESENCE UNAVAILABLE" }); });
    return () => { active = false; };
  }, [path]);
  const gateError = useCallback(() => setState({ kind: "HUMAN PRESENCE UNAVAILABLE" }), []);
  const onToken = useCallback((token: string) => {
    const current = generation.current;
    setState({ kind: "VERIFYING" });
    void (async () => {
      try {
        const response = await fetch(`/api/v1${path}/challenge`, { method: "POST", cache: "no-store", credentials: "omit", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token }) });
        if (!response.ok) {
          if (current === generation.current) setState({ kind: response.status === 404 ? "RECEIPT NOT FOUND" : "HUMAN PRESENCE UNAVAILABLE" });
          return;
        }
        const grant = await response.json();
        const next = await fetchReceipt(path, grant.access_token);
        if (current === generation.current) { setAccessToken(grant.access_token); setState(next); }
      } catch { if (current === generation.current) gateError(); }
    })();
  }, [path, gateError]);
  async function verifyAgain() {
    setState({ kind: "VERIFYING" });
    setState(await fetchReceipt(path, accessToken));
  }
  async function acknowledge() {
    setAck("SENDING…");
    try {
      const response = await fetch(`/api/v1${path}/acknowledge`, { method: "POST", cache: "no-store", credentials: "omit", headers: { Authorization: `Bearer ${accessToken}` } });
      setAck(response.ok ? "ACKNOWLEDGED" : "ACKNOWLEDGEMENT UNAVAILABLE");
    } catch { setAck("ACKNOWLEDGEMENT UNAVAILABLE"); }
  }
  const label = state.kind === "READY" ? verificationLabel(state.receipt, receiptHash(path)!) : state.kind;
  return <main className="tc-page"><article className="tc-receipt"><header className="tc-header"><p>PRAMA—DYNAMAGH</p><h1>TITULAR CHECK</h1><span>VERIFIABLE AGENT RECEIPT / V0</span></header>
    {state.kind === "HUMAN PRESENCE REQUIRED" && siteKey && <TurnstileGate siteKey={siteKey} hash={receiptHash(path)!} onToken={onToken} onError={gateError} />}
    {state.kind === "READY" && <ReceiptBody receipt={state.receipt} hash={receiptHash(path)!} label={label} />}
    <section className="tc-verdict" aria-live="polite"><h2>TITULAR VERIFICATION</h2><p className={label === "VERIFIED" ? "tc-verified" : "tc-alert"}>{label}</p>{state.kind === "READY" && <><button className="tc-verify" type="button" onClick={() => void verifyAgain()}>VERIFY AGAIN</button><button className="tc-verify tc-ack" type="button" disabled={ack === "ACKNOWLEDGED" || ack === "SENDING…"} onClick={() => void acknowledge()}>{ack || "ACKNOWLEDGE"}</button><p className="tc-note">Acknowledgement confirms receipt, not approval of the action.</p></>}{state.kind === "HUMAN PRESENCE UNAVAILABLE" && siteKey && <button className="tc-verify" type="button" onClick={() => setState({ kind: "HUMAN PRESENCE REQUIRED" })}>RETRY HUMAN CHECK</button>}</section>
    <footer className="tc-footer"><p>PRAMA—DYNAMAGH</p><span>VERIFIABLE AGENT RECEIPT</span><p className="tc-note">Verification checks the persisted artifact and its sources. The Decision above retains its own authority.</p></footer>
  </article></main>;
}
