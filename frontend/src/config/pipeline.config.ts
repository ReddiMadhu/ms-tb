// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Pipeline Configuration — Single source of truth
// Edit this file to add/rename/reorder stages.
// Aligned with backend orchestrator.py PIPELINE_STAGES (20 stages)
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

export interface PipelineStageConfig {
  id: string;
  number: number;
  title: string;
  shortTitle: string;
  description: string;
  icon: string;          // lucide icon name
  color: string;
}

export const PIPELINE_STAGES: PipelineStageConfig[] = [
  {
    id: 'DISCOVERY',
    number: 1,
    title: 'Discovery',
    shortTitle: 'Discovery',
    description: 'Scan MSTR project — find dossiers, reports, metrics, attributes, cubes',
    icon: 'Search',
    color: 'var(--blue)',
  },
  {
    id: 'GRAPH',
    number: 2,
    title: 'Dependency Analysis',
    shortTitle: 'Graph',
    description: 'Build relationships and dependency graph between objects',
    icon: 'GitBranch',
    color: 'var(--blue)',
  },
  {
    id: 'SEMANTIC',
    number: 3,
    title: 'Semantic Extraction',
    shortTitle: 'Semantic',
    description: 'Extract data model — dimensions, measures, hierarchies',
    icon: 'Layers',
    color: 'var(--blue)',
  },
  {
    id: 'METRIC_DEDUPLICATION',
    number: 4,
    title: 'Metric Deduplication',
    shortTitle: 'Dedup',
    description: 'Identify and deduplicate equivalent metric definitions',
    icon: 'Copy',
    color: 'var(--blue)',
  },
  {
    id: 'IR_COMPILE',
    number: 5,
    title: 'IR Compilation',
    shortTitle: 'IR Compile',
    description: 'Compile MSTR definitions into portable intermediate representation',
    icon: 'Code',
    color: 'var(--primary)',
  },
  {
    id: 'AI_TRANSLATE',
    number: 6,
    title: 'Expression Translation',
    shortTitle: 'Translate',
    description: 'Translate MSTR expressions into Tableau calculated fields',
    icon: 'Sparkles',
    color: 'var(--primary)',
  },
  {
    id: 'VIZ',
    number: 7,
    title: 'Visualization Planning',
    shortTitle: 'Viz Plan',
    description: 'Plan dashboard and worksheet reconstruction',
    icon: 'LayoutDashboard',
    color: 'var(--primary)',
  },
  {
    id: 'HYPER_BUILD',
    number: 8,
    title: 'Data Extract Build',
    shortTitle: 'Hyper',
    description: 'Build Hyper data extracts from source data',
    icon: 'Database',
    color: 'var(--green)',
  },
  {
    id: 'DATASOURCE_EMIT',
    number: 9,
    title: 'Datasource Generation',
    shortTitle: 'Datasource',
    description: 'Generate Tableau datasource definitions (.tds)',
    icon: 'FileOutput',
    color: 'var(--green)',
  },
  {
    id: 'DATASOURCE_PUBLISH',
    number: 10,
    title: 'Datasource Publish',
    shortTitle: 'DS Publish',
    description: 'Publish generated datasources to Tableau staging environment',
    icon: 'Upload',
    color: 'var(--green)',
  },
  {
    id: 'WORKBOOK_EMIT_STAGING',
    number: 11,
    title: 'Workbook Generation',
    shortTitle: 'Workbook',
    description: 'Generate Tableau workbooks with dashboards and worksheets',
    icon: 'FileSpreadsheet',
    color: 'var(--green)',
  },
  {
    id: 'STAGING_PUBLISH',
    number: 12,
    title: 'Staging Publish',
    shortTitle: 'Stage Pub',
    description: 'Publish workbook to Tableau staging server for validation',
    icon: 'CloudUpload',
    color: 'var(--green)',
  },
  {
    id: 'SERVER_RENDER_VALIDATE',
    number: 13,
    title: 'Server Render Validation',
    shortTitle: 'Render Check',
    description: 'Validate server-side rendering of published workbooks on Tableau',
    icon: 'MonitorCheck',
    color: 'var(--yellow)',
  },
  {
    id: 'STATIC_VALIDATE',
    number: 14,
    title: 'Structural Validation',
    shortTitle: 'Validate',
    description: 'Validate all artifacts — structural checks and schema compliance',
    icon: 'ShieldCheck',
    color: 'var(--yellow)',
  },
  {
    id: 'SECURITY_VALIDATE',
    number: 15,
    title: 'Security Validation',
    shortTitle: 'Security',
    description: 'Validate security parity — RLS filters, permission mapping, access controls',
    icon: 'Lock',
    color: 'var(--yellow)',
  },
  {
    id: 'NUMERIC_VALIDATE',
    number: 16,
    title: 'Numeric Validation',
    shortTitle: 'Numeric',
    description: 'Validate numeric parity — KPI values, aggregation accuracy, decimal precision',
    icon: 'Calculator',
    color: 'var(--yellow)',
  },
  {
    id: 'WORKBOOK_EMIT_PRODUCTION',
    number: 17,
    title: 'Production Workbook Emit',
    shortTitle: 'Prod Emit',
    description: 'Generate production-ready workbook with validated configurations',
    icon: 'PackageCheck',
    color: 'var(--green)',
  },
  {
    id: 'PROMOTE',
    number: 18,
    title: 'Production Promotion',
    shortTitle: 'Promote',
    description: 'Promote validated workbooks from staging to production environment',
    icon: 'ArrowUpCircle',
    color: 'var(--green)',
  },
  {
    id: 'RECONCILE',
    number: 19,
    title: 'Reconciliation',
    shortTitle: 'Reconcile',
    description: 'Post-promotion reconciliation — verify published assets and cleanup staging',
    icon: 'CheckCheck',
    color: 'var(--green)',
  },
  {
    id: 'REPORT',
    number: 20,
    title: 'Report Generation',
    shortTitle: 'Report',
    description: 'Generate migration report and final package',
    icon: 'FileText',
    color: 'var(--green)',
  },
];

export const PIPELINE_STAGE_COUNT = PIPELINE_STAGES.length;

export function getStageConfig(stageId: string): PipelineStageConfig | undefined {
  return PIPELINE_STAGES.find(s => s.id === stageId);
}

export function getStageIndex(stageId: string): number {
  return PIPELINE_STAGES.findIndex(s => s.id === stageId);
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Phase Grouping — 4 lifecycle phases that aggregate the 20 stages
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

export interface PhaseConfig {
  id: string;
  number: number;
  title: string;
  description: string;
  icon: string;          // lucide icon name
  color: string;
  stageIds: string[];    // ordered child stage IDs
  subViews: { label: string; key: string }[];
}

export const PIPELINE_PHASES: PhaseConfig[] = [
  {
    id: 'EXTRACTION_CATALOG',
    number: 1,
    title: 'Dashboard Intelligence',
    description: 'Parse MicroStrategy objects, build object model & dependency graph',
    icon: 'Search',
    color: 'var(--blue)',
    stageIds: ['DISCOVERY', 'GRAPH'],
    subViews: [
      { label: 'Object Catalog', key: 'objects' },
    ],
  },
  {
    id: 'SEMANTIC_LOGIC',
    number: 2,
    title: 'Calculation Logic Conversion',
    description: 'Analyze expressions, convert MSTR formulas to Tableau calculated fields',
    icon: 'Layers',
    color: 'var(--primary)',
    stageIds: ['SEMANTIC', 'METRIC_DEDUPLICATION', 'IR_COMPILE', 'AI_TRANSLATE'],
    subViews: [
      { label: 'Calculation Logic Conversion', key: 'logic' },
    ],
  },
  {
    id: 'TARGET_BUILD',
    number: 3,
    title: 'Visual Conversion Report',
    description: 'Side-by-side MicroStrategy to Tableau visual conversion, artifact generation & staging publish',
    icon: 'FileSpreadsheet',
    color: 'var(--green)',
    stageIds: ['VIZ', 'HYPER_BUILD', 'DATASOURCE_EMIT', 'DATASOURCE_PUBLISH', 'WORKBOOK_EMIT_STAGING', 'STAGING_PUBLISH'],
    subViews: [
      { label: 'Visual Conversion Report', key: 'dashboards' },
    ],
  },
  {
    id: 'QUALITY_PACKAGE',
    number: 4,
    title: 'Publish & Export Center',
    description: 'Multi-gate validation, production promotion, reconciliation & export',
    icon: 'ShieldCheck',
    color: 'var(--yellow)',
    stageIds: ['SERVER_RENDER_VALIDATE', 'STATIC_VALIDATE', 'SECURITY_VALIDATE', 'NUMERIC_VALIDATE', 'WORKBOOK_EMIT_PRODUCTION', 'PROMOTE', 'RECONCILE', 'REPORT'],
    subViews: [
      { label: 'Export Center', key: 'exports' },
    ],
  },
];

export function getPhaseForStage(stageId: string): PhaseConfig | undefined {
  return PIPELINE_PHASES.find(p => p.stageIds.includes(stageId));
}

export function getPhaseConfig(phaseId: string): PhaseConfig | undefined {
  return PIPELINE_PHASES.find(p => p.id === phaseId);
}

/**
 * Compute aggregated status for a phase from its child stage statuses.
 * Priority: FAILED > RUNNING > WARNING > COMPLETED > WAITING
 */
export function getPhaseStatus(
  phaseId: string,
  stageStatuses: Record<string, string>,
): string {
  const phase = getPhaseConfig(phaseId);
  if (!phase) return 'WAITING';

  const statuses = phase.stageIds.map(id => stageStatuses[id] || 'WAITING');

  if (statuses.some(s => s === 'FAILED')) return 'FAILED';
  if (statuses.some(s => s === 'RUNNING')) return 'RUNNING';
  if (statuses.some(s => s === 'WARNING')) return 'WARNING';
  if (statuses.every(s => s === 'COMPLETED')) return 'COMPLETED';
  if (statuses.some(s => s === 'COMPLETED')) return 'RUNNING'; // partially complete
  return 'WAITING';
}

/**
 * Get the currently active sub-stage label for a phase.
 * Returns the stage config of the currently running stage within the phase, if any.
 */
export function getActiveSubStage(
  phaseId: string,
  stageStatuses: Record<string, string>,
): PipelineStageConfig | null {
  const phase = getPhaseConfig(phaseId);
  if (!phase) return null;

  for (const stageId of phase.stageIds) {
    if (stageStatuses[stageId] === 'RUNNING') {
      return getStageConfig(stageId) || null;
    }
  }
  return null;
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Job Lifecycle & Status Helpers
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

export const TERMINAL_JOB_STATUSES = [
  'COMPLETE',
  'COMPLETE_WITH_WARNINGS',
  'PUBLISHED',
  'FAILED',
  'CANCELLED',
];

export function isJobTerminal(status?: string): boolean {
  if (!status) return false;
  return TERMINAL_JOB_STATUSES.includes(status);
}

export function isJobRunning(status?: string): boolean {
  if (!status) return false;
  return !isJobTerminal(status);
}

