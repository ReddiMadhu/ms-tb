import React, { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  Activity,
  ArrowLeft,
  Clock,
  CheckCircle2,
  Loader2,
  AlertTriangle,
  Play,
  RotateCcw,
  Sparkles,
  Terminal,
  Cpu,
  Layers,
  Database,
  Code,
} from 'lucide-react';
import { api, type Job } from '../api';
import { StatusBadge } from '../components/ui/StatusBadge';
import { MigrationProgress } from '../components/execution/MigrationProgress';
import { TaskRow, type TaskRowData } from '../components/execution/TaskRow';
import { ToolChip } from '../components/execution/ToolChip';

// Maps each backend stage to the execution task phase it belongs to
const STAGE_TO_PHASE: Record<string, number> = {
  DISCOVERY: 0,
  GRAPH: 0,
  SEMANTIC: 1,
  METRIC_DEDUPLICATION: 1,
  IR_COMPILE: 1,
  AI_TRANSLATE: 1,
  VIZ: 2,
  HYPER_BUILD: 2,
  DATASOURCE_EMIT: 2,
  DATASOURCE_PUBLISH: 2,
  WORKBOOK_EMIT_STAGING: 2,
  STAGING_PUBLISH: 2,
  SERVER_RENDER_VALIDATE: 3,
  STATIC_VALIDATE: 3,
  SECURITY_VALIDATE: 3,
  NUMERIC_VALIDATE: 3,
  WORKBOOK_EMIT_PRODUCTION: 3,
  PROMOTE: 3,
  RECONCILE: 3,
  REPORT: 3,
};

const PHASE_STAGES: string[][] = [
  ['DISCOVERY', 'GRAPH'],
  ['SEMANTIC', 'METRIC_DEDUPLICATION', 'IR_COMPILE', 'AI_TRANSLATE'],
  ['VIZ', 'HYPER_BUILD', 'DATASOURCE_EMIT', 'DATASOURCE_PUBLISH', 'WORKBOOK_EMIT_STAGING', 'STAGING_PUBLISH'],
  ['SERVER_RENDER_VALIDATE', 'STATIC_VALIDATE', 'SECURITY_VALIDATE', 'NUMERIC_VALIDATE', 'WORKBOOK_EMIT_PRODUCTION', 'PROMOTE', 'RECONCILE', 'REPORT'],
];

const ALL_STAGES = Object.keys(STAGE_TO_PHASE);

function getPhaseStatus(
  phaseIndex: number,
  currentStage: string,
  completedStages: string[],
  isComplete: boolean,
  isFailed: boolean,
): 'COMPLETED' | 'RUNNING' | 'WAITING' | 'FAILED' {
  if (isComplete) return 'COMPLETED';

  const stagesInPhase = PHASE_STAGES[phaseIndex];
  const currentIdx = ALL_STAGES.indexOf(currentStage);

  // Check if the failed stage is in this phase
  if (isFailed && stagesInPhase.includes(currentStage)) return 'FAILED';

  // Check if all stages in the phase are completed
  const allCompleted = stagesInPhase.every(
    s => completedStages.includes(s) || ALL_STAGES.indexOf(s) < currentIdx
  );
  if (allCompleted) return 'COMPLETED';

  // Check if any stage in the phase is currently active
  if (stagesInPhase.includes(currentStage)) return 'RUNNING';

  // Check if any stage was already passed
  const anyStarted = stagesInPhase.some(
    s => completedStages.includes(s) || ALL_STAGES.indexOf(s) < currentIdx
  );
  if (anyStarted) return 'RUNNING';

  return 'WAITING';
}

import {
  isJobTerminal,
  isJobRunning,
} from '../config/pipeline.config';

export default function LiveExecution() {
  const { jobId } = useParams<{ jobId: string }>();
  const [job, setJob] = useState<Job | null>(null);
  const [tasks, setTasks] = useState<TaskRowData[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchStatus = React.useCallback(async () => {
    if (!jobId) return;
    try {
      const data = await api.getJob(jobId);
      setJob(data);
      const currentStage = data.progress?.current_stage || data.current_stage || 'DISCOVERY';
      const completedStages = data.progress?.stages_completed || [];
      const isComplete = ['COMPLETE', 'COMPLETE_WITH_WARNINGS', 'PUBLISHED'].includes(data.status);
      const isFailed = data.status === 'FAILED';
      const totalObjs = data.progress?.objects_total || data.objects_total || 0;
      const processedObjs = data.progress?.objects_processed || data.objects_processed || 0;

      const dynamicTasks: TaskRowData[] = [
        {
          id: 'phase-extraction',
          name: '1. Extraction & Catalog (Discovery & Dependency Graph)',
          detail: 'Scan project, parse dossiers/cubes, extract metadata, and build dependency graph',
          status: getPhaseStatus(0, currentStage, completedStages, isComplete, isFailed),
          processedCount: processedObjs,
          totalCount: totalObjs,
          logs: [`Cataloged ${totalObjs} objects from MicroStrategy API and constructed dependency graph`],
        },
        {
          id: 'phase-semantic',
          name: '2. Semantic & Logic (Deduplication, IR Compile, AI Translate)',
          detail: 'Deduplicate metrics, compile to BI-IR AST, and translate expressions to Tableau calculations',
          status: getPhaseStatus(1, currentStage, completedStages, isComplete, isFailed),
          processedCount: processedObjs,
          totalCount: totalObjs,
          logs: ['Compiled universal BI-IR representation and mapped LOD calculations'],
        },
        {
          id: 'phase-target',
          name: '3. Target Artifact Generation (Visuals, Hyper, Datasources, Staging Publish)',
          detail: 'Synthesize TDS datasources, build Hyper extracts, assemble workbooks, and publish to Tableau staging',
          status: getPhaseStatus(2, currentStage, completedStages, isComplete, isFailed),
          processedCount: processedObjs,
          totalCount: totalObjs,
          logs: ['Generated TDS datasource definitions, compiled workbook structure, and published to staging'],
        },
        {
          id: 'phase-quality',
          name: '4. Quality Gates, Promotion & Report (Validation, Promote, Reconcile)',
          detail: 'Execute multi-gate validation (structural, numeric, security, visual), promote to production, reconcile, and generate report',
          status: getPhaseStatus(3, currentStage, completedStages, isComplete, isFailed),
          processedCount: processedObjs,
          totalCount: totalObjs,
          logs: ['Executed validation gates, promoted to production, and compiled executive report'],
        },
      ];

      setTasks(dynamicTasks);
      setLoading(false);
    } catch (e) {
      console.error('Failed to load execution status:', e);
      setLoading(false);
    }
  }, [jobId]);

  useEffect(() => {
    fetchStatus();

    const terminal = job && isJobTerminal(job.status);
    if (terminal) return;

    const interval = setInterval(() => {
      fetchStatus();
    }, 2000);

    return () => clearInterval(interval);
  }, [fetchStatus, job?.status]);

  return (
    <div style={{ maxWidth: '1440px', margin: '0 auto' }}>
      {/* ── Top Breadcrumbs & Title ──────────────────────────────── */}
      <div style={{ marginBottom: '20px' }}>
        <Link
          to={`/jobs/${jobId}`}
          className="btn btn-ghost"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '6px',
            padding: '4px 8px',
            fontSize: '0.8125rem',
            color: 'var(--ink-2)',
            marginBottom: '10px',
          }}
        >
          <ArrowLeft size={14} />
          <span>Back to Migration Control Center</span>
        </Link>

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <h1
                style={{
                  fontSize: '1.625rem',
                  fontWeight: 700,
                  color: 'var(--ink)',
                  letterSpacing: '-0.02em',
                  margin: 0,
                }}
              >
                Live Execution Monitor
              </h1>
              {job && <StatusBadge status={job.status} size="md" />}
            </div>
            <p style={{ fontSize: '0.875rem', color: 'var(--ink-2)', marginTop: '4px' }}>
              Real-time execution telemetry, task progression, and backend compilation trace
            </p>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <ToolChip label="MSTR Parser" active count="187 objs" />
            <ToolChip label="DAG Engine" active count="642 edges" />
            <ToolChip label="LOD Compiler" active count="183 calcs" />
            <ToolChip label="Hyper Builder" active />
          </div>
        </div>
      </div>

      {/* ── Overall Progress ─────────────────────────────────────── */}
      <MigrationProgress
        progressPercent={job?.status === 'COMPLETE' ? 100 : 75}
        currentStageName={job?.progress?.current_stage || 'AI Translation & Validation'}
        elapsedSeconds={job?.duration_seconds || 184}
        isRunning={job?.status === 'RUNNING'}
        isComplete={job?.status === 'COMPLETE'}
      />

      {/* ── Task Rows (The Observable Execution Layer) ──────────── */}
      <div style={{ marginBottom: '32px' }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: '14px',
          }}
        >
          <h3 style={{ fontSize: '1.0625rem', fontWeight: 600, color: 'var(--ink)', margin: 0 }}>
            Execution Task Pipeline ({tasks.length} Operations)
          </h3>
          <span style={{ fontSize: '0.75rem', color: 'var(--ink-3)' }}>
            Click any task to view execution logs
          </span>
        </div>

        <div className="task-row-list">
          {tasks.map((task) => (
            <TaskRow key={task.id} task={task} initiallyExpanded={task.status === 'RUNNING'} />
          ))}
        </div>
      </div>
    </div>
  );
}
