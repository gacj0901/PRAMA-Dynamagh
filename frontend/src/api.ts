export type Json = Record<string, unknown>;

export interface Mandate {
  mandate_id: string;
  actor_id: string;
  text: string;
  mandate_type: string;
  constraints: Json;
  max_budget_usdc: string | number;
  deadline: string | null;
  status: string;
  origin: string;
  autonomy_policy_id: string | null;
  autonomy_run_id: string | null;
  created_at: string;
  updated_at: string;
  acquisitions?: Acquisition[];
}

export interface Acquisition {
  acquisition_id: string;
  status: string;
  intent?: string | null;
  miner_id?: string | null;
  miner_name?: string | null;
  signal_hash?: string | null;
  cost_usd?: number | null;
  duration_ms?: number | null;
}

export interface Evidence {
  evidence_id: string;
  admissibility: string;
  provenance_status: string;
  content_hash: string;
  source_intent: string | null;
  source_miner_id: string | null;
  source_signal_hash: string | null;
  limitation_codes: string[];
  normalized_payload: Json;
}

export interface Evaluation {
  evaluation_id: string;
  evaluator_version: string;
  evidence_set_hash: string;
  structural_state: string;
  limitation_codes: string[];
  contradiction_codes: string[];
}

export interface Decision {
  decision_id: string;
  state: string;
  policy_version: string;
  evidence_set_hash: string;
  reason_codes: string[];
  evaluation_id: string;
}

export interface Ticket {
  ticket_id: string;
  mandate_id: string;
  schema_version: string;
  ticket_hash: string;
  anchor_status: string;
  canonical_payload: Json;
}

export interface TicketVerification {
  ticket_id: string;
  status: string;
  payload_hash_match: boolean;
  source_artifacts_match: boolean;
  failure_codes: string[];
}

export interface Anchor {
  ticket_id: string;
  anchor_status: string;
  anchor_attempt: {
    anchor_attempt_id: string;
    status: string;
    chain_id: number;
    contract_address: string;
    tx_hash: string | null;
    block_number: number | null;
    block_hash: string | null;
    failure_code: string | null;
  } | null;
}

export interface Erc8183Job {
  erc8183_job_id: string;
  mandate_id: string | null;
  ticket_id: string | null;
  chain_id: number;
  diamond_address: string;
  telegraph_job_id: string | null;
  intent_name: string;
  callback_address: string;
  callback_response_hash: string | null;
  callback_verified: boolean;
  state: string;
  chain_state: string | null;
  budget_usdc: string | number | null;
  miner_payment_usdc: string | number | null;
  protocol_fee_usdc: string | number | null;
  output_hash: string | null;
  create_tx_hash: string | null;
  terminal_tx_hash: string | null;
  created_at: string;
  updated_at: string;
}

export interface Lineage {
  erc8183_job_id: string;
  telegraph_job_id: string | null;
  telegraph_output_hash: string | null;
  callback_response_hash: string | null;
  callback_verified: boolean;
  intent_id: string | null;
  terminal_tx_hash: string | null;
  evidence_id: string | null;
  evidence_content_hash: string | null;
  evaluation_id: string | null;
  evidence_set_hash: string | null;
  decision_id: string | null;
  decision_state: string | null;
  ticket_id: string | null;
  ticket_hash: string | null;
  anchor_status: string | null;
}

export interface AutonomyPolicy {
  policy_id: string;
  name: string;
  enabled: boolean;
  version: string;
  mandate_template: Json;
  acquisition_mode: string;
  allow_telegraph_http: boolean;
  allow_erc8183: boolean;
  allow_anchor: boolean;
  strict_verification: boolean;
  read_only_replay: boolean;
  cadence_seconds: number;
  dedupe_window_seconds: number;
  max_usdc_per_run: string | number;
  max_usdc_per_day: string | number;
  max_runs_per_day: number;
  max_concurrent_runs: number;
  state: string;
  last_run_at: string | null;
  next_run_at: string | null;
}

export interface AutonomyRun {
  run_id: string;
  policy_id: string;
  state: string;
  mandate_id: string | null;
  erc8183_job_id: string | null;
  ticket_id: string | null;
  planned_cost_usdc: string | number;
  actual_cost_usdc: string | number;
  scheduled_for: string;
  finished_at: string | null;
}

export interface AutonomyStatus {
  global_enabled: boolean;
  active_policy_count: number;
  active_run_count: number;
  today_run_count: number;
  today_spend_usdc: string | number;
  next_due_at: string | null;
  autonomous_runs_total: number;
  completed: number;
  skipped: number;
  failed: number;
  actual_usdc_spend: string | number;
}

export interface Timeline {
  mandate_id: string;
  transitions: Array<{ transition_id: string; from_status: string | null; to_status: string; reason: string | null; created_at: string }>;
  events: Array<{ event_id: string; event_type: string; acquisition_id: string | null; metadata: Json; created_at: string }>;
}

export interface MandateDetails {
  mandate: Mandate;
  acquisitions: Acquisition[];
  evidence: Evidence[];
  evaluation: Evaluation | null;
  decision: Decision | null;
  ticket: Ticket | null;
  verification: TicketVerification | null;
  anchor: Anchor | null;
  timeline: Timeline | null;
}

export interface PublicActivity {
  budget_profile: {
    configured_max_usdc_per_workflow: string;
    effective_max_usdc_per_workflow: string;
    configured_daily_spend_cap_usdc: string;
    effective_daily_spend_cap_usdc: string;
    max_single_acquisition_usdc: string;
    max_real_calls_per_workflow: number;
    multi_intent_enabled: boolean;
    g12_hard_cap_applied: boolean;
    operator_approval_required_for_raise: boolean;
  };
  scope: {
    included_origins: string[];
    excluded_origins: string[];
    test_classification: string;
  };
  real_users: number;
  workflows_started: number;
  workflows_completed: number;
  returning_users: number;
  telegraph_calls: number;
  telegraph_successful_calls: number;
  real_miners_used: string[];
  intents_used: string[];
  multi_intent_workflows: number;
  evidence_created: number;
  decisions_emitted: number;
  tickets_emitted: number;
  autonomous_runs: number;
  completion_rate: number;
  average_calls_per_workflow: number;
  average_evidence_per_workflow: number;
  average_latency_ms: number | null;
  public_spend_usdc: string | number;
}

export interface PublicTicketSummary {
  share_schema: string;
  workflow: {
    mandate_id: string;
    mandate_type: string;
    origin: string;
    status: string;
    summary: string;
    created_at: string | null;
  };
  acquisitions: Array<{ acquisition_id: string; status: string; intent: string | null; miner: string | null; cost_usdc: string; duration_ms: number | null }>;
  evidence: Array<{ evidence_id: string; admissibility: string; provenance_status: string; source_intent: string | null; content_hash: string }>;
  evaluation: { structural_state: string; limitations: string[]; contradictions: string[] } | null;
  decision: { state: string; reason_codes: string[] } | null;
  ticket: { ticket_id: string; schema_version: string; ticket_hash: string; anchor_status: string; created_at: string | null };
  limitations: string[];
  verification: { status: string; url: string };
  replay: { status: string; url: string };
}

const API_PREFIX = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_PREFIX}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`${response.status}: ${detail || response.statusText}`);
  }
  return response.json() as Promise<T>;
}

async function optional<T>(path: string): Promise<T | null> {
  try {
    return await request<T>(path);
  } catch (error) {
    if (error instanceof Error && error.message.startsWith("404:")) return null;
    throw error;
  }
}

export const api = {
  health: () => request<{ status: string; service: string }>("/health"),
  mandates: () => request<Mandate[]>("/v1/mandates"),
  jobs: () => request<Erc8183Job[]>("/v1/erc8183/jobs"),
  policies: () => request<AutonomyPolicy[]>("/v1/autonomy/policies"),
  runs: () => request<AutonomyRun[]>("/v1/autonomy/runs"),
  autonomy: () => request<AutonomyStatus>("/v1/autonomy/status"),
  activity: () => request<PublicActivity>("/v1/public/activity"),
  ticketShare: (ticketId: string) => request<PublicTicketSummary>(`/v1/tickets/${ticketId}/share`),
  lineage: (jobId: string) => optional<Lineage>(`/v1/erc8183/jobs/${jobId}/lineage`),
  mandateDetails: async (mandateId: string): Promise<MandateDetails> => {
    const mandate = await request<Mandate>(`/v1/mandates/${mandateId}`);
    const [acquisitionResponse, evidence, evaluation, decision, ticket, timeline] = await Promise.all([
      request<{ acquisitions: Acquisition[] }>(`/v1/mandates/${mandateId}/acquisitions`),
      request<Evidence[]>(`/v1/mandates/${mandateId}/evidence`),
      optional<Evaluation>(`/v1/mandates/${mandateId}/evaluation`),
      optional<Decision>(`/v1/mandates/${mandateId}/decision`),
      optional<Ticket>(`/v1/mandates/${mandateId}/ticket`),
      optional<Timeline>(`/v1/mandates/${mandateId}/timeline`),
    ]);
    const verification = ticket ? await optional<TicketVerification>(`/v1/tickets/${ticket.ticket_id}/verify`) : null;
    const anchor = ticket ? await optional<Anchor>(`/v1/tickets/${ticket.ticket_id}/anchor`) : null;
    return { mandate, acquisitions: acquisitionResponse.acquisitions, evidence, evaluation, decision, ticket, verification, anchor, timeline };
  },
  createMandate: (payload: Pick<Mandate, "actor_id" | "text" | "mandate_type" | "constraints" | "max_budget_usdc">) =>
    request<Mandate>("/v1/mandates", { method: "POST", body: JSON.stringify(payload) }),
  setPolicyEnabled: (policyId: string, enabled: boolean) => request<AutonomyPolicy>(`/v1/autonomy/policies/${policyId}/${enabled ? "enable" : "disable"}`, { method: "POST" }),
  patchPolicy: (policyId: string, payload: Partial<Pick<AutonomyPolicy, "strict_verification" | "read_only_replay" | "allow_anchor">>) =>
    request<AutonomyPolicy>(`/v1/autonomy/policies/${policyId}`, { method: "PATCH", body: JSON.stringify(payload) }),
};
