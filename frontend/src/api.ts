const API_BASE = 'http://localhost:8000/api/v1';

async function fetchJSON<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${url}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  return res.json();
}

// ── Types ─────────────────────────────────────────────────────

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

// ── API functions ─────────────────────────────────────────────

export const api = {
  // Status
  getStatus: () => fetchJSON<{ status: string; database: string; template_version: string }>('/status'),

  // Jobs
  listJobs: () => fetchJSON<{ jobs: Job[]; total: number }>('/jobs'),
  getJob: (id: string) => fetchJSON<Job>(`/jobs/${id}`),
  createJob: (data: Partial<Job>) => fetchJSON<Job>('/jobs', { method: 'POST', body: JSON.stringify(data) }),
  cancelJob: (id: string) => fetchJSON<void>(`/jobs/${id}/cancel`, { method: 'POST' }),

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
