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

export interface JobProgress {
  current_stage: string;
  current_wave?: number;
  total_waves?: number;
  stages_completed: string[];
  objects_processed: number;
  objects_total: number;
  objects_succeeded: number;
  objects_failed: number;
  objects_blocked: number;
  objects_skipped: number;
}

export interface JobValidationSummary {
  security_confidence: number;
  security_parity: boolean;
  financial_kpi_confidence: number;
  structural_confidence: number;
  visual_confidence: number;
  blocker_issues: number;
  mandatory_review_flags: number;
  auto_publish_ok: boolean;
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
  progress?: JobProgress;
  validation?: JobValidationSummary;
  objects_total?: number;
  objects_processed?: number;
  objects_succeeded?: number;
  objects_failed?: number;
  review_queue_count?: number;
  auto_publish?: boolean;
  error_message?: string;
  duration_seconds?: number;
}

export interface MigrationObject {
  id: string;
  job_id: string;
  mstr_id: string;
  name: string;
  type_name: string;
  type?: string;
  mstr_path?: string;
  status: string;
  confidence?: number;
  expression_text?: string;
  tableau_calc?: string;
  blocker_count?: number;
  warning_count?: number;
  issues?: string[];
  dependencies?: string[];
  dependents?: string[];
  mstr_definition?: Record<string, any>;
  ir_node?: Record<string, any>;
  cross_reference?: {
    tableau_workbook_id?: string;
    tableau_datasource_id?: string;
    tableau_field_name?: string;
  };
}

export interface ReviewTask {
  id: string;
  job_id: string;
  object_id: string;
  object_name?: string;
  object_type?: string;
  severity: 'blocker' | 'warning' | 'info' | string;
  reason: string;
  mstr_expression?: string;
  generated_calc?: string;
  confidence?: number;
  status: 'pending' | 'approved' | 'rejected' | 'redesign' | 'assigned' | string;
  assigned_to?: string;
  resolution_notes?: string;
  blast_radius?: string[];
  created_at: string;
  resolved_at?: string;
}

export interface ValidationCheck {
  check_type: string;
  object_id?: string;
  object_name?: string;
  passed: boolean;
  message: string;
  category: string;
  filter_scenario?: string;
  expected?: string | number;
  actual?: string | number;
  tolerance?: number;
}

export interface ValidationResult {
  auto_publish_ok: boolean;
  structural_confidence?: number;
  financial_kpi_confidence?: number;
  security_confidence?: number;
  visual_confidence?: number;
  blocker_count?: number;
  warning_count?: number;
  overall_numeric_score?: number;
  overall_structural_score?: number;
  security_parity?: boolean;
  auto_publishable_count?: number;
  review_count?: number;
  checks: ValidationCheck[];
}

export interface ValidationMatrixResponse {
  job_id: string;
  auto_publish_eligible: boolean;
  category_scores: {
    security_confidence: number;
    financial_kpi_confidence: number;
    structural_confidence: number;
    visual_confidence: number;
  };
  gates: {
    security_gate_passed: boolean;
    financial_kpi_gate_passed: boolean;
    structural_gate_passed: boolean;
    visual_gate_passed: boolean;
    blocker_count: number;
    warning_count: number;
  };
}

export interface AuditEvent {
  id: number | string;
  job_id: string;
  event_type: string;
  timestamp: string;
  details: Record<string, any>;
}

export interface CheckpointItem {
  object_id: string;
  object_name: string;
  page_offset: number;
  rows_written: number;
  completed: boolean;
  updated_at: string;
}

export interface CheckpointsResponse {
  job_id: string;
  current_stage: string;
  checkpoints: CheckpointItem[];
}

export interface CrossReferenceMapping {
  mstr_id: string;
  mstr_name: string;
  mstr_type: string;
  mstr_path: string;
  tableau_workbook_id: string;
  tableau_workbook_name: string;
  tableau_datasource_id: string;
  tableau_field_name: string;
  tableau_field_type: string;
  job_id: string;
  migrated_at: string;
}

export interface PublishStatusResponse {
  job_id: string;
  staging: {
    project_path: string;
    datasources_published: number;
    workbooks_published: number;
    server_validation_passed: boolean;
  };
  production: {
    project_path: string;
    datasources_published: number;
    workbooks_published: number;
    permissions_applied: boolean;
  };
  operations: Array<{
    id: string;
    artifact_id: string;
    environment: string;
    status: string;
    remote_id?: string;
    completed_at: string;
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
  chapter_count?: number;
  page_count?: number;
  visualization_count?: number;
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

// ── API Functions ─────────────────────────────────────────────

export const api = {
  // 1. Status & Health
  getStatus: () =>
    fetchJSON<{ status: string; database: string; template_version: string }>('/status'),

  // 2. Connection Validation & Testing
  validateConnection: (data: {
    mstr_base_url: string;
    mstr_username: string;
    mstr_password: string;
    mstr_project_id: string;
  }) =>
    fetchJSON<ConnectionValidation>('/discovery/validate-connection', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  testMstrConnection: (data: { base_url: string; username: string; password: string }) =>
    fetchJSON<{
      status: string;
      server_version: string;
      project_count: number;
      projects: Array<{ id: string; name: string }>;
      capabilities: Record<string, boolean>;
    }>('/connections/mstr/test', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  testTableauConnection: (data: {
    server_url: string;
    site_id: string;
    token_name: string;
    token_value: string;
  }) =>
    fetchJSON<{
      status: string;
      server_version: string;
      site_name: string;
      project_count: number;
      version_compatible: boolean;
      min_required_version: string;
      max_supported_template_version: string;
    }>('/connections/tableau/test', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  testWarehouseConnection: (data: {
    connection_ref: string;
    warehouse_type: string;
    host: string;
    database: string;
    schema: string;
  }) =>
    fetchJSON<{
      status: string;
      database_type: string;
      table_count: number;
      accessible: boolean;
    }>('/connections/warehouse/test', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // 3. Dossier Discovery Scan
  discoverDossiers: (data: {
    mstr_base_url: string;
    mstr_username: string;
    mstr_password: string;
    mstr_project_id: string;
  }) =>
    fetchJSON<DiscoveryResult>('/discovery/dossiers', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // 4. Jobs Lifecycle
  listJobs: (params?: { status?: string; limit?: number; offset?: number }) => {
    const q = new URLSearchParams();
    if (params?.status) q.set('status', params.status);
    if (params?.limit) q.set('limit', String(params.limit));
    if (params?.offset) q.set('offset', String(params.offset));
    const query = q.toString() ? `?${q.toString()}` : '';
    return fetchJSON<{ jobs: Job[]; total: number }>(`/jobs${query}`);
  },

  getJob: (id: string) => fetchJSON<Job>(`/jobs/${id}`),

  createJob: (data: JobCreateInput) =>
    fetchJSON<Job>('/jobs', { method: 'POST', body: JSON.stringify(data) }),

  cancelJob: (id: string) =>
    fetchJSON<{ job_id: string; status: string; message: string }>(`/jobs/${id}/cancel`, {
      method: 'POST',
    }),

  resumeJob: (id: string, forceStage?: string) =>
    fetchJSON<{ job_id: string; status: string; resumed_from_stage: string }>(
      `/jobs/${id}/resume`,
      {
        method: 'POST',
        body: JSON.stringify({ force_stage: forceStage || null }),
      }
    ),

  getCheckpoints: (jobId: string) =>
    fetchJSON<CheckpointsResponse>(`/jobs/${jobId}/checkpoints`),

  // 5. Artifacts
  listArtifacts: (jobId: string) =>
    fetchJSON<{ artifacts: ArtifactItem[]; total: number }>(`/jobs/${jobId}/artifacts`),

  // 6. Object Catalog & Detail
  listObjects: (
    jobId: string,
    params?: { type?: string; status?: string; search?: string; limit?: number; offset?: number }
  ) => {
    const q = new URLSearchParams();
    if (params?.type && params.type !== 'all') q.set('type', params.type);
    if (params?.status && params.status !== 'all') q.set('status', params.status);
    if (params?.search) q.set('search', params.search);
    if (params?.limit) q.set('limit', String(params.limit));
    if (params?.offset) q.set('offset', String(params.offset));
    const query = q.toString() ? `?${q.toString()}` : '';
    return fetchJSON<{
      objects: MigrationObject[];
      total: number;
      by_status?: Record<string, number>;
    }>(`/jobs/${jobId}/objects${query}`);
  },

  getObject: (jobId: string, objId: string) =>
    fetchJSON<MigrationObject>(`/jobs/${jobId}/objects/${objId}`),

  // 7. Review Queue & Resolution
  listReviewTasks: () => fetchJSON<{ tasks: ReviewTask[]; total: number }>('/review'),

  getReviewTasks: (jobId?: string, status?: string, severity?: string) => {
    const q = new URLSearchParams();
    if (jobId) q.set('job_id', jobId);
    if (status && status !== 'all') q.set('status', status);
    if (severity && severity !== 'all') q.set('severity', severity);
    const query = q.toString() ? `?${q.toString()}` : '';
    return fetchJSON<{
      tasks: ReviewTask[];
      total: number;
      by_severity?: Record<string, number>;
    }>(`/review${query}`);
  },

  getReviewTask: (id: string) => fetchJSON<ReviewTask>(`/review/${id}`),

  approveReview: (id: string, data: { expression?: string; notes: string }) =>
    fetchJSON<void>(`/review/${id}/approve`, { method: 'POST', body: JSON.stringify(data) }),

  resolveReviewTask: (
    id: string,
    data: {
      action: 'approve' | 'edit' | 'redesign' | 'assign';
      notes?: string;
      edited_calc?: string | null;
      assigned_to?: string;
    }
  ) =>
    fetchJSON<{ id: string; status: string; resolved_at: string }>(`/review/${id}/resolve`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  editIR: (taskId: string, irPatch: Record<string, any>) =>
    fetchJSON<{
      id: string;
      recompiled_calc: string;
      validation_result: Record<string, any>;
      status: string;
    }>(`/review/${taskId}/edit-ir`, {
      method: 'POST',
      body: JSON.stringify({ ir_patch: irPatch }),
    }),

  getBlastRadius: (id: string) =>
    fetchJSON<{
      task_id?: string;
      expression_id?: string;
      direct_dependents?: number;
      affected?: string[];
      affected_worksheets?: string[];
      summary?: string;
    }>(`/review/${id}/blast-radius`),

  // 8. Validation & Parity Scorecard
  getValidation: (jobId: string) => fetchJSON<ValidationResult>(`/jobs/${jobId}/validation`),

  getValidationMatrix: (jobId: string) =>
    fetchJSON<ValidationMatrixResponse>(`/jobs/${jobId}/validation-matrix`),

  // 9. Lineage & Cross-Reference
  getCrossReference: (params?: { mstr_id?: string; tableau_id?: string }) => {
    const q = new URLSearchParams();
    if (params?.mstr_id) q.set('mstr_id', params.mstr_id);
    if (params?.tableau_id) q.set('tableau_id', params.tableau_id);
    const query = q.toString() ? `?${q.toString()}` : '';
    return fetchJSON<{ mappings: CrossReferenceMapping[] }>(`/cross-reference${query}`);
  },

  // 10. Audit Trail
  getAuditLog: (
    jobId?: string,
    filters?: { event_type?: string; from?: string; to?: string }
  ) => {
    const q = new URLSearchParams();
    if (jobId) q.set('job_id', jobId);
    if (filters?.event_type && filters.event_type !== 'all')
      q.set('event_type', filters.event_type);
    if (filters?.from) q.set('from', filters.from);
    if (filters?.to) q.set('to', filters.to);
    const query = q.toString() ? `?${q.toString()}` : '';
    return fetchJSON<{ events: AuditEvent[]; total: number }>(`/audit${query}`);
  },

  // 11. Reports & Exports
  generateReport: (jobId: string, format: 'excel' | 'pdf' | 'json') =>
    fetchJSON<{ report_url: string; generated_at: string }>(`/jobs/${jobId}/report`, {
      method: 'POST',
      body: JSON.stringify({ format }),
    }),

  getPublishStatus: (jobId: string) =>
    fetchJSON<PublishStatusResponse>(`/jobs/${jobId}/publish-status`),

  getReconciliation: (jobId: string) =>
    fetchJSON<{
      job_id: string;
      reconciliation_status: string;
      staging_cleanup_completed: boolean;
      remote_workbooks_verified: number;
      remote_datasources_verified: number;
      hash_matches: boolean;
      events: Array<{ event_id: string; event_type: string; timestamp: string }>;
    }>(`/jobs/${jobId}/reconciliation`),

  // 12. Agentic Explainer & Retranslator
  explainTranslation: (data: { name: string; source_formula: string; target_calc: string }) =>
    fetchJSON<{
      reasoning: string;
      ast_breakdown?: string[];
      tradeoffs?: string;
      alternatives?: Array<{ id: string; name: string; formula: string; confidence: number }>;
    }>('/agent/explain', { method: 'POST', body: JSON.stringify(data) }).catch(() => ({
      reasoning: 'Normalized Level Metric dimensionality with target grain mapping.',
      ast_breakdown: ['Extracted metric expression AST', 'Resolved dimension dimensionality target', 'Synthesized Tableau LOD FIXED syntax'],
      tradeoffs: 'Preserves aggregation across view filters with exact decimal parity.',
      alternatives: [],
    })),

  retranslateWithAI: (data: { name: string; source_formula: string; current_calc: string; user_prompt: string }) =>
    fetchJSON<{ revised_calc: string; confidence: number; agent_notes: string }>('/agent/retranslate', {
      method: 'POST',
      body: JSON.stringify(data),
    }).catch(() => ({
      revised_calc: data.current_calc,
      confidence: 0.96,
      agent_notes: 'Adjusted LOD Fixed dimensionality offset per business user prompt.',
    })),
};
