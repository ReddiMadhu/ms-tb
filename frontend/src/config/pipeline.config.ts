// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Pipeline Configuration — Single source of truth
// Edit this file to add/rename/reorder stages.
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
    description: 'Generate Tableau datasource definitions',
    icon: 'FileOutput',
    color: 'var(--green)',
  },
  {
    id: 'WORKBOOK_EMIT_STAGING',
    number: 10,
    title: 'Workbook Generation',
    shortTitle: 'Workbook',
    description: 'Generate Tableau workbooks with dashboards and worksheets',
    icon: 'FileSpreadsheet',
    color: 'var(--green)',
  },
  {
    id: 'STATIC_VALIDATE',
    number: 11,
    title: 'Validation',
    shortTitle: 'Validate',
    description: 'Validate all artifacts — structural, numeric, security, visual checks',
    icon: 'ShieldCheck',
    color: 'var(--yellow)',
  },
  {
    id: 'REPORT',
    number: 12,
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
// Phase Grouping — 4 lifecycle phases that aggregate the 12 stages
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
    title: 'Extraction & Catalog',
    description: 'Discover objects and map dependency graph',
    icon: 'Search',
    color: 'var(--blue)',
    stageIds: ['DISCOVERY', 'GRAPH'],
    subViews: [
      { label: 'Object Catalog', key: 'objects' },
      { label: 'Lineage Explorer', key: 'lineage' },
    ],
  },
  {
    id: 'SEMANTIC_LOGIC',
    number: 2,
    title: 'Semantic & Logic',
    description: 'Extract semantics, deduplicate, compile & translate',
    icon: 'Layers',
    color: 'var(--primary)',
    stageIds: ['SEMANTIC', 'METRIC_DEDUPLICATION', 'IR_COMPILE', 'AI_TRANSLATE'],
    subViews: [
      { label: 'Semantic Model', key: 'semantic' },
      { label: 'Logic & Calculations', key: 'logic' },
    ],
  },
  {
    id: 'TARGET_BUILD',
    number: 3,
    title: 'Target Artifact Generation',
    description: 'Plan visualizations, build extracts, emit datasources & workbooks',
    icon: 'FileSpreadsheet',
    color: 'var(--green)',
    stageIds: ['VIZ', 'HYPER_BUILD', 'DATASOURCE_EMIT', 'WORKBOOK_EMIT_STAGING'],
    subViews: [
      { label: 'Dashboard Inventory', key: 'dashboards' },
      { label: 'Export Center', key: 'exports' },
    ],
  },
  {
    id: 'QUALITY_PACKAGE',
    number: 4,
    title: 'Quality & Final Package',
    description: 'Validate all artifacts and generate migration report',
    icon: 'ShieldCheck',
    color: 'var(--yellow)',
    stageIds: ['STATIC_VALIDATE', 'REPORT'],
    subViews: [
      { label: 'Validation Center', key: 'validation' },
      { label: 'Issue Review Queue', key: 'review' },
      { label: 'Migration Report', key: 'report' },
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
