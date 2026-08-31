/**
 * Server-side data access for the BFF.
 *
 * Every page is a Server Component that fetches here, so no API base URL, and no
 * credential of any kind, reaches the browser bundle.
 */

const BASE = process.env.NIGHTSHIFT_API_URL ?? "http://127.0.0.1:8081";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly path: string,
  ) {
    super(message);
  }
}

async function get<T>(path: string, revalidate = 5): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    next: { revalidate },
    headers: { accept: "application/json" },
  });
  if (!response.ok) {
    throw new ApiError(
      `${response.status} ${response.statusText}`,
      response.status,
      path,
    );
  }
  return (await response.json()) as T;
}

/**
 * The outcome of a request that must not throw.
 *
 * A 404 and a 502 are different facts about the world. Collapsing them makes a page
 * announce "no such incident" when the truth is that the API fell over, which is the
 * one thing this product claims never to do.
 */
export interface Fetched<T> {
  data: T | null;
  /** True only for a 404. An upstream or network failure leaves this false. */
  missing: boolean;
  /** Set when the request failed for any reason other than a 404. */
  failure: ApiError | null;
}

export async function tryGetResult<T>(path: string, revalidate = 5): Promise<Fetched<T>> {
  try {
    return { data: await get<T>(path, revalidate), missing: false, failure: null };
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return { data: null, missing: true, failure: null };
    }
    return {
      data: null,
      missing: false,
      failure:
        error instanceof ApiError
          ? error
          : new ApiError(error instanceof Error ? error.message : String(error), 0, path),
    };
  }
}

/** Returns null instead of throwing, for surfaces that must degrade rather than 500. */
export async function tryGet<T>(path: string, revalidate = 5): Promise<T | null> {
  return (await tryGetResult<T>(path, revalidate)).data;
}

// --- types ---------------------------------------------------------------------------

export interface Meta {
  synthetic: boolean;
  simulated_field_events: boolean;
  disclaimer: string;
  model_id: string;
  model_location: string;
  adk_version: string;
  region: string;
  deployment_env: string;
  source_commit: string;
  store_backend: string;
  signer_backend: string;
  model_armor_configured: boolean;
  tracing: { enabled: boolean; requested: boolean; project_id: string; exporter: string };
  evaluated_at: string;
}

export interface FreezerRow {
  freezer_id: string;
  label: string;
  zone: string;
  state: string;
  current_temp_c: number;
  setpoint_c: number;
  alarm_high_c: number;
  above_alarm: boolean;
  total_slots: number;
  occupied_slots: number;
  free_slots: number;
  is_backup_qualified: boolean;
  reading_age_s: number;
  hold_active: boolean;
}

export interface IncidentCard {
  incident_id: string;
  state: string;
  severity: string;
  failed_freezer_id: string;
  opened_at: string;
  closed_at: string | null;
  impacted_containers: number;
  committed: number;
  unresolved: number;
  in_flight: number;
  complete: boolean;
}

export interface Overview {
  evaluated_at: string;
  active_incidents: number;
  total_incidents: number;
  freezers: FreezerRow[];
  capacity: {
    total_slots: number;
    occupied_slots: number;
    reserved_slots: number;
    backup_free_slots: number;
  };
  incidents: IncidentCard[];
}

export interface InvariantResult {
  invariant: string;
  title: string;
  holds: boolean;
  detail: string;
  evidence: Record<string, unknown>;
}

export interface Receipt {
  receipt_id: string;
  action_id: string;
  action_type: string;
  actor_identity: string;
  requested_by_agent: string | null;
  status: string;
  failure_class: string;
  refusal_reason: string | null;
  committed_at: string;
  duplicate_returned: boolean;
  effect_ref: string | null;
  evidence_sources: string[];
  trace_id: string | null;
}

export interface TimelineEvent {
  event_id: string;
  occurred_at: string;
  source: string;
  kind: string;
  summary: string;
  detail: Record<string, unknown>;
  action_id: string | null;
  agent: string | null;
  trace_id: string | null;
}

export interface IncidentDetail {
  incident: {
    id: string;
    state: string;
    severity: string;
    failed_freezer_id: string;
    opened_at: string;
    closed_at: string | null;
    unresolved_count: number;
    namespace: string;
    transitions: {
      from_state: string;
      to_state: string;
      at: string;
      reason: string;
    }[];
  };
  evaluated_at: string;
  /** The instant the hard invariants were asked about, which is not always now. */
  evaluated_as_of: string;
  /** Why that instant: "incident closed_at", "sealed manifest evaluated_at", or "wall clock". */
  evaluation_basis: string;
  trace: {
    root_trace_id: string | null;
    trace_ids: string[];
    console_url: string;
    enabled: boolean;
  };
  freezer: FreezerRow | null;
  temperature_series: { id: string; celsius: number; recorded_at: string }[];
  impact: {
    id: string;
    specimen_total: number;
    container_ids: string[];
    study_ids: string[];
    priority_breakdown: Record<string, number>;
    snapshot_hash: string;
    placement_groups: {
      id: string;
      priority_class: number;
      required_temp_c: number;
      slot_count: number;
    }[];
  } | null;
  reconciliation: {
    total: number;
    committed: string[];
    quarantined: string[];
    unresolved: string[];
    in_flight: string[];
    complete: boolean;
    hash: string;
  };
  reservations: {
    id: string;
    destination_freezer_id: string;
    placement_group_id: string;
    slots: number;
    slots_remaining: number | null;
    state: string;
  }[];
  work_orders: { id: string; freezer_id: string; fault_class: string; status: string; summary: string }[];
  dispatches: { id: string; responder_id: string; responder_role: string; response_phase: string; status: string }[];
  transfers: {
    transfer_id: string;
    container_id: string;
    source_freezer: string;
    destination_freezer: string;
    destination_slot: string;
    state: string;
    destination_temp_c: number | null;
    exception_reason: string | null;
  }[];
  receipts: Receipt[];
  invariants: InvariantResult[];
  containers: {
    container_id: string;
    freezer_id: string;
    study_id: string;
    priority_class: number;
    specimen_count: number;
    custody_state: string;
  }[];
}

export interface FleetAgent {
  agent: string;
  revision: string;
  qualification: string;
  traffic_percent: number;
  identity: string | null;
  /**
   * Where `identity` came from, so the page can say it without overclaiming.
   * "provisioned-service-account" is the account the gateway mints this agent's
   * outbound OIDC token as. It is not a live Agent Registry read.
   */
  identity_source?: "agent-registry-snapshot" | "provisioned-service-account" | "none" | null;
  runtime_resource: string | null;
  registry_resource: string | null;
  latest_drill: {
    revision: string;
    covered_by_run: string | null;
    outcome: string;
    corpus_version: string | null;
    scope: string;
  } | null;
  authority_domains: string[];
  allowed_tools: string[];
  forbidden_tools: string[];
  permissions: Record<string, string>;
}

export interface Fleet {
  evaluated_at: string;
  agents: FleetAgent[];
  permission_matrix: Record<string, Record<string, string>>;
  skills: { name: string; revision: string; content_sha256: string; managed_resource: string | null }[];
  tool_registry: { name: string; service: string; domain: string; mutating: boolean; description: string }[];
}

export interface DrillSummary {
  id: string;
  family: string;
  title: string;
  description: string;
  holdout: boolean;
  requires_model: boolean;
  faults: { tool: string; call_number: number; kind: string }[];
  expectations: { key: string; description: string }[];
  results: Record<string, { runs: number; passed: number; failed: number; failed_invariants: string[] }>;
}

export interface CampaignBlock {
  runs: number;
  scored_runs: number;
  infrastructure_errors: number;
  passed: number;
  failed: number;
  pass_rate: number | null;
  capacity_overbooking_violations: number;
  duplicate_effect_violations: number;
  invalid_custody_violations: number;
  premature_close_violations: number;
  authority_violations: number;
  memory_authority_violations: number;
  runs_with_injected_faults: number;
  faults_injected_total: number;
  runs_with_duplicate_effect_after_fault: number;
  runs_fully_reconciled: number;
  runs_closed: number;
  authorization_denials_total: number;
  duplicate_receipts_returned: number;
  containers_committed_total: number;
  wall_clock_median_s: number | null;
  wall_clock_p95_s: number | null;
  per_drill: Record<string, { runs: number; passed: number; failed: number }>;
}

export interface Drills {
  corpus_version: string;
  drills: DrillSummary[];
  campaign: { total_runs: number; by_driver: Record<string, CampaignBlock> };
  provenance: Record<string, unknown>;
}

export interface EvidenceIndex {
  manifests: {
    incident_id: string;
    incident_state: string;
    evaluated_at: string;
    signer_backend: string;
    invariants_all_hold: boolean;
    failed_invariants: string[];
    reconciliation: { total: number; committed: string[]; unresolved: string[] };
    verification_status: string;
  }[];
  campaign_metrics: { total_runs: number; by_driver: Record<string, CampaignBlock> };
  campaign_provenance: Record<string, unknown>;
  claims: {
    id: string;
    claim: string;
    status: string;
    evidence: string;
    reproduce: string;
    limitation: string;
  }[];
}

export interface Proof {
  incident_id: string;
  manifest: Record<string, unknown>;
  manifest_hash: string | null;
  gcs_uri: string | null;
  verification: {
    status: string;
    checks: { name: string; result: string; detail: string }[];
    recomputed_invariants: Record<string, boolean>;
    stored_invariants: Record<string, boolean>;
    divergences: string[];
  };
  verify_command: string;
}

export interface ResponderTask {
  container_id: string;
  source_freezer: string;
  source_slot: string;
  destination_freezer: string | null;
  destination_slot: string | null;
  custody_state: string;
  destination_temp_c: number | null;
  destination_reading_age_s: number | null;
  exception_reason: string | null;
}

export interface ResponderView {
  incident_id: string;
  incident_state: string;
  responder_id: string;
  responder_role: string;
  response_phase: string;
  failed_freezer_id: string;
  evaluated_at: string;
  synthetic: boolean;
  tasks: ResponderTask[];
  summary: {
    total: number;
    at_source: number;
    picked_up: number;
    received: number;
    committed: number;
    exceptions: number;
  };
}

// --- fetchers ------------------------------------------------------------------------

export const getMeta = () => tryGet<Meta>("/api/meta", 60);
export const getOverview = () => tryGet<Overview>("/api/overview", 3);
export const getIncident = (id: string) => tryGetResult<IncidentDetail>(`/api/incidents/${id}`, 3);
export const getTimeline = (id: string) =>
  tryGet<{ events: TimelineEvent[]; count: number }>(`/api/incidents/${id}/timeline`, 3);
export const getProof = (id: string) => tryGet<Proof>(`/api/incidents/${id}/proof`, 30);
export const getFleet = () => tryGet<Fleet>("/api/fleet", 30);
export const getDrills = () => tryGet<Drills>("/api/drills", 30);
export const getDrill = (id: string) =>
  tryGetResult<{ drill: DrillSummary; runs: Record<string, unknown>[]; run_count: number }>(
    `/api/drills/${id}`,
    30,
  );
export const getEvidence = () => tryGet<EvidenceIndex>("/api/evidence", 30);
export const getResponderView = (token: string) =>
  tryGet<ResponderView>(`/api/respond/${token}`, 0);
