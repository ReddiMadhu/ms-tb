// Use relative URL so Vite's proxy (vite.config.ts) handles the routing to the backend
const API_BASE = '/api/v1';

async function fetchJSON<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${url}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  return res.json();
}

// ── Types ─────────────────────────────────────────────────────

export interface JobCreateInput {
  name: string;
  mstr_base_url: string;
  mstr_username: string;
  mstr_password: string;
  mstr_project_id: string;
  tableau_server_url?: string;
  tableau_site_id?: string;
  tableau_target_project?: string;
  template_version?: string;
  skip_unused?: boolean;
  extract_data?: boolean;
  auto_publish?: boolean;
  publish_mode?: string;
  numeric_threshold?: number;
  selected_dossier_ids?: string[];
  warehouse_connection?: Record<string, any>;
}

export interface Job {
  id: string;
  name: string;
  status: string;
  mstr_base_url: string;
  mstr_project_id: string;
  tableau_server_url?: string;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  current_stage?: string;
  objects_total?: number;
  objects_processed?: number;
  auto_publish?: boolean;
  error_message?: string;
}

export interface MigrationObject {
  id: string;
  job_id: string;
  mstr_id: string;
  name: string;
  type_name: string;
  mstr_path?: string;
  status: string;
  confidence?: number;
  expression_text?: string;
  tableau_calc?: string;
  blocker_count?: number;
  warning_count?: number;
}

export interface ReviewTask {
  id: string;
  job_id: string;
  object_id: string;
  severity: string;
  reason: string;
  mstr_expression?: string;
  generated_calc?: string;
  confidence?: number;
  status: string;
  assigned_to?: string;
  resolution_notes?: string;
  created_at: string;
  resolved_at?: string;
}

export interface ValidationResult {
  auto_publish_ok: boolean;
  structural_confidence?: number;
  financial_kpi_confidence?: number;
  security_confidence?: number;
  visual_confidence?: number;
  blocker_count?: number;
  warning_count?: number;
  checks: Array<{
    check_type: string;
    object_id: string;
    passed: boolean;
    message: string;
    category: string;
  }>;
}

export interface MSTRProject {
  id: string;
  name: string;
  description?: string;
  status?: number;
  alias?: string;
}

export interface ConnectionValidation {
  valid: boolean;
  project_name?: string;
  server_version?: string;
  projects?: MSTRProject[];
  error?: string;
}

export interface DiscoveredDossier {
  mstr_id: string;
  name: string;
  path?: string;
  description?: string;
  owner?: string;
  date_modified?: string;
  datasets: string[];
  metric_count: number;
  attribute_count: number;
}

export interface DiscoveryResult {
  dossiers: DiscoveredDossier[];
  total: number;
  scan_duration_ms: number;
}

export interface ArtifactItem {
  id: string;
  type: string;
  file_name: string;
  file_path: string;
  size_bytes: number;
  artifact_hash: string;
  environment: string;
}

// ── API functions ─────────────────────────────────────────────

export const api = {
  // Status
  getStatus: () => fetchJSON<{ status: string; database: string; template_version: string }>('/status'),

  // Connection Validation
  validateConnection: (data: {
    mstr_base_url: string;
    mstr_username: string;
    mstr_password: string;
    mstr_project_id: string;
  }) => fetchJSON<ConnectionValidation>('/discovery/validate-connection', {
    method: 'POST',
    body: JSON.stringify(data),
  }),

  // Dossier Discovery
  discoverDossiers: (data: {
    mstr_base_url: string;
    mstr_username: string;
    mstr_password: string;
    mstr_project_id: string;
  }) => fetchJSON<DiscoveryResult>('/discovery/dossiers', {
    method: 'POST',
    body: JSON.stringify(data),
  }),

  // Jobs
  listJobs: () => fetchJSON<{ jobs: Job[]; total: number }>('/jobs'),
  getJob: (id: string) => fetchJSON<Job>(`/jobs/${id}`),
  createJob: (data: JobCreateInput) => fetchJSON<Job>('/jobs', { method: 'POST', body: JSON.stringify(data) }),
  cancelJob: (id: string) => fetchJSON<void>(`/jobs/${id}/cancel`, { method: 'POST' }),

  // Artifacts
  listArtifacts: (jobId: string) => fetchJSON<{ artifacts: ArtifactItem[]; total: number }>(`/jobs/${jobId}/artifacts`),

  // Objects
  listObjects: (jobId: string) => fetchJSON<{ objects: MigrationObject[]; total: number }>(`/jobs/${jobId}/objects`),
  getObject: (jobId: string, objId: string) => fetchJSON<MigrationObject>(`/jobs/${jobId}/objects/${objId}`),

  // Review
  listReviewTasks: () => fetchJSON<{ tasks: ReviewTask[]; total: number }>('/review'),
  getReviewTask: (id: string) => fetchJSON<ReviewTask>(`/review/${id}`),
  approveReview: (id: string, data: { expression?: string; notes: string }) =>
    fetchJSON<void>(`/review/${id}/approve`, { method: 'POST', body: JSON.stringify(data) }),
  getBlastRadius: (id: string) => fetchJSON<{ affected: string[] }>(`/review/${id}/blast-radius`),

  // Validation
  getValidation: (jobId: string) => fetchJSON<ValidationResult>(`/jobs/${jobId}/validation`),
};
