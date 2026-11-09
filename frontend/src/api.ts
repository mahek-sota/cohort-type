export type Evidence = "codes" | "labs" | "both";

/** Matches the backend's Judgments model. Judgments that don't apply must be left out. */
export interface Judgments {
  evidence: Evidence;
  include_diagnosis?: boolean;
  include_complications?: boolean;
  include_other_complications?: boolean;
  include_prediabetes?: boolean;
  hba1c_threshold?: number | null;
}

export interface Preset {
  id: string;
  name: string;
  judgments: Judgments;
  rationale: string;
}

export interface CohortPatient {
  id: string;
  evidence_rows: number;
}

export interface Cohort {
  count: number;
  population: number;
  percent: number;
  patients: CohortPatient[];
}

/** One source row that qualified a patient. `row` is the line number in `table`'s CSV. */
export interface EvidenceRow {
  table: "conditions" | "observations";
  row: number;
  code: string;
  description: string;
  value: string | null;
  units: string | null;
  date: string;
}

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new Error(`Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export async function fetchPresets(): Promise<Preset[]> {
  return readJson(await fetch("/api/presets"));
}

export async function fetchCohort(judgments: Judgments, signal: AbortSignal): Promise<Cohort> {
  const response = await fetch("/api/cohort", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(judgments),
    signal,
  });
  return readJson(response);
}

export async function fetchEvidence(
  patientId: string,
  judgments: Judgments,
  signal: AbortSignal,
): Promise<EvidenceRow[]> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(judgments)) {
    if (value !== null && value !== undefined) {
      params.set(key, String(value));
    }
  }
  const url = `/api/patients/${encodeURIComponent(patientId)}/evidence?${params}`;
  const body = await readJson<{ evidence: EvidenceRow[] }>(await fetch(url, { signal }));
  return body.evidence;
}

export type AgentName = "naive" | "context";

export interface TranscriptStep {
  type: "text" | "tool_call";
  text?: string;
  name?: string;
  input?: unknown;
  result?: string;
  is_error?: boolean;
}

export interface AgentRun {
  agent: AgentName;
  run: number;
  steps: TranscriptStep[];
  score: { headline_number: number | null } | null;
}

export interface AgentSummary {
  runs: number;
  gave_a_count: number;
  stated_definition: number;
  flagged_ambiguity: number;
  invented_numbers: number;
  headline_numbers: Record<string, number>;
}

export interface ReviewCounts {
  gave_valid_count: number;
  named_definition: number;
  flagged_ambiguity: number;
  compared_definitions: number;
  invented_numbers: number;
}

/** Written for one specific run, not by the script. `make agents` drops it, so it may be absent. */
export interface DecodedAnswer {
  agent: AgentName;
  number: number;
  runs: number;
  said: string;
  counted: string;
  disclosed: string;
  judgments: Judgments | null;
}

export interface AgentReview {
  counts: Record<AgentName, ReviewCounts>;
  notes: string[];
  decoded?: DecodedAnswer[];
}

export interface AgentResults {
  question: string;
  backend: string;
  model: string;
  generated_at: string;
  summary: Record<AgentName, AgentSummary>;
  examples: Record<AgentName, AgentRun | null>;
  runs: AgentRun[];
  review?: AgentReview;
}

export async function fetchAgentRuns(): Promise<AgentResults | null> {
  const body = await readJson<{ available: boolean; results: AgentResults | null }>(
    await fetch("/api/agent-runs"),
  );
  return body.available ? body.results : null;
}

export interface LiveStatus {
  enabled: boolean;
  backend: string | null;
  model: string | null;
}

export interface LiveDecoding {
  status: "match" | "rows_not_patients" | "no_match" | "no_count";
  reported: number | null;
  patients: number | null;
  judgments: Judgments | null;
}

export interface LiveAnswer {
  answer: string | null;
  steps: TranscriptStep[];
  error: string | null;
  used_tools: boolean;
  decoding: LiveDecoding;
}

export async function fetchLiveStatus(): Promise<LiveStatus> {
  return readJson(await fetch("/api/live/status"));
}

export async function askLive(
  question: string,
  agent: AgentName,
  signal: AbortSignal,
): Promise<LiveAnswer> {
  const response = await fetch("/api/live/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, agent }),
    signal,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Request failed (${response.status})`);
  }
  return response.json();
}
