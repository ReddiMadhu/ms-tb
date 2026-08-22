import React, { useEffect, useState, useMemo } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  ArrowLeft,
  Loader2,
} from 'lucide-react';
import { api, type Job, type AuditEvent } from '../api';
import { StatusBadge } from '../components/ui/StatusBadge';
import { MigrationProgress } from '../components/execution/MigrationProgress';
import { TaskRow, type TaskRowData } from '../components/execution/TaskRow';
import { ToolChip } from '../components/execution/ToolChip';
import {
  isJobTerminal,
  isJobRunning,
  getStageConfig,
  getStageIndex,
  PIPELINE_STAGE_COUNT,
} from '../config/pipeline.config';

// Maps each backend stage to the execution task phase it belongs to (0: Extraction, 1: Semantic, 2: Target, 3: Quality)
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
  DATASOURCE_PUBLISH_STAGING: 2,
  WORKBOOK_EMIT_STAGING: 2,
  STAGING_PUBLISH: 2,
  SERVER_RENDER_VALIDATE: 3,
  STATIC_VALIDATE: 3,
  SECURITY_VALIDATE: 3,
  NUMERIC_VALIDATE: 3,
  WORKBOOK_EMIT_PRODUCTION: 3,
  DATASOURCE_PUBLISH_PRODUCTION: 3,
  PROMOTE: 3,
  RECONCILE: 3,
  REPORT: 3,
};

const PHASE_STAGES: string[][] = [
  ['DISCOVERY', 'GRAPH'],
  ['SEMANTIC', 'METRIC_DEDUPLICATION', 'IR_COMPILE', 'AI_TRANSLATE'],
  ['VIZ', 'HYPER_BUILD', 'DATASOURCE_EMIT', 'DATASOURCE_PUBLISH', 'DATASOURCE_PUBLISH_STAGING', 'WORKBOOK_EMIT_STAGING', 'STAGING_PUBLISH'],
  ['SERVER_RENDER_VALIDATE', 'STATIC_VALIDATE', 'SECURITY_VALIDATE', 'NUMERIC_VALIDATE', 'WORKBOOK_EMIT_PRODUCTION', 'DATASOURCE_PUBLISH_PRODUCTION', 'PROMOTE', 'RECONCILE', 'REPORT'],
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
    s => completedStages.includes(s) || (currentIdx >= 0 && ALL_STAGES.indexOf(s) < currentIdx)
  );
  if (allCompleted) return 'COMPLETED';

  // Check if any stage in the phase is currently active
  if (stagesInPhase.includes(currentStage)) return 'RUNNING';

  // Check if any stage was already passed
  const anyStarted = stagesInPhase.some(
    s => completedStages.includes(s) || (currentIdx >= 0 && ALL_STAGES.indexOf(s) < currentIdx)
  );
  if (anyStarted) return 'RUNNING';

  return 'WAITING';
}

function getPhaseLogs(
  phaseIndex: number,
  events: AuditEvent[],
  phaseStatus: 'COMPLETED' | 'RUNNING' | 'WAITING' | 'FAILED',
  totalObjs: number,
  processedObjs: number,
): string[] {
  const phaseStages = PHASE_STAGES[phaseIndex];

  const matchingEvents = events.filter((e) => {
    const stage = String(e.details?.stage || e.details?.current_stage || '').toUpperCase();
    if (stage && phaseStages.includes(stage)) return true;

    const eventType = String(e.event_type || '').toUpperCase();
    if (phaseStages.some((s) => eventType.includes(s))) return true;

    if (phaseIndex === 0 && (eventType.includes('DISCOVERY') || eventType.includes('GRAPH') || eventType.includes('SCAN') || eventType.includes('PARSE'))) return true;
    if (phaseIndex === 1 && (eventType.includes('SEMANTIC') || eventType.includes('DEDUP') || eventType.includes('IR_') || eventType.includes('TRANSLAT') || eventType.includes('CALC') || eventType.includes('LOD'))) return true;
    if (phaseIndex === 2 && (eventType.includes('VIZ') || eventType.includes('HYPER') || eventType.includes('DATASOURCE') || eventType.includes('WORKBOOK') || eventType.includes('STAGING'))) return true;
    if (phaseIndex === 3 && (eventType.includes('VALIDAT') || eventType.includes('SECURITY') || eventType.includes('NUMERIC') || eventType.includes('RENDER') || eventType.includes('PROMOTE') || eventType.includes('RECONCILE') || eventType.includes('REPORT') || eventType.includes('GATE'))) return true;

    return false;
  });

  if (matchingEvents.length > 0) {
    return matchingEvents.map((e) => {
      const timeStr = e.timestamp
        ? new Date(e.timestamp).toLocaleTimeString('en-US', { hour12: false })
        : '';
      const msg =
        e.details?.message ||
        e.details?.description ||
        e.details?.summary ||
        (e.details && Object.keys(e.details).length > 0 ? JSON.stringify(e.details) : e.event_type);
      return timeStr ? `[${timeStr}] ${msg}` : msg;
    });
  }

  // Dynamic status messages if no specific audit logs exist yet
  if (phaseStatus === 'COMPLETED') {
    if (phaseIndex === 0) {
      return totalObjs > 0
        ? [`Discovered ${totalObjs} MicroStrategy objects and resolved dependency graph`]
        : ['Cataloged MicroStrategy objects and constructed dependency graph'];
    }
    if (phaseIndex === 1) return ['Compiled universal BI-IR representation and mapped LOD calculations'];
    if (phaseIndex === 2) return ['Generated TDS datasources, built Hyper extract, and published to staging'];
    if (phaseIndex === 3) return ['Executed validation gates, promoted to production, and generated final report'];
  }

  if (phaseStatus === 'RUNNING') {
    if (phaseIndex === 0) {
      return [`Analyzing MicroStrategy objects (${processedObjs}/${totalObjs || '?'} processed)...`];
    }
    if (phaseIndex === 1) return ['Compiling IR models and translating calculations...'];
    if (phaseIndex === 2) return ['Generating Tableau artifacts and building extracts...'];
    if (phaseIndex === 3) return ['Executing validation gates and checking parity...'];
  }

  if (phaseStatus === 'FAILED') {
    return ['Pipeline execution encountered errors in this phase. Check audit trail for details.'];
  }

  return ['Phase waiting in queue...'];
}

export default function LiveExecution() {
  const { jobId } = useParams<{ jobId: string }>();
  const [job, setJob] = useState<Job | null>(null);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [tasks, setTasks] = useState<TaskRowData[]>([]);
  const [loading, setLoading] = useState(true);
  const [currentTime, setCurrentTime] = useState(Date.now());

  // Tick timer every second for running jobs
  useEffect(() => {
    if (job && !isJobTerminal(job.status)) {
      const timer = setInterval(() => setCurrentTime(Date.now()), 1000);
      return () => clearInterval(timer);
    }
  }, [job?.status]);

  const fetchStatus = React.useCallback(async () => {
    if (!jobId) return;
    try {
      const [jobRes, auditRes] = await Promise.allSettled([
        api.getJob(jobId),
        api.getAuditLog(jobId),
      ]);

      if (jobRes.status === 'fulfilled') {
        const data = jobRes.value;
        setJob(data);

        const events = auditRes.status === 'fulfilled' ? (auditRes.value?.events || []) : [];
        setAuditEvents(events);

        const currentStage = data.progress?.current_stage || data.current_stage || 'DISCOVERY';
        const completedStages = data.progress?.stages_completed || [];
        const isComplete = ['COMPLETE', 'COMPLETE_WITH_WARNINGS', 'PUBLISHED'].includes(data.status);
        const isFailed = data.status === 'FAILED';
        const totalObjs = data.progress?.objects_total || data.objects_total || 0;
        const processedObjs = data.progress?.objects_processed || data.objects_processed || 0;

        const phase0Status = getPhaseStatus(0, currentStage, completedStages, isComplete, isFailed);
        const phase1Status = getPhaseStatus(1, currentStage, completedStages, isComplete, isFailed);
        const phase2Status = getPhaseStatus(2, currentStage, completedStages, isComplete, isFailed);
        const phase3Status = getPhaseStatus(3, currentStage, completedStages, isComplete, isFailed);

        const dynamicTasks: TaskRowData[] = [
          {
            id: 'phase-extraction',
            name: '1. Extraction & Catalog (Discovery & Dependency Graph)',
            detail: 'Scan project, parse dossiers/cubes, extract metadata, and build dependency graph',
            status: phase0Status,
            processedCount: processedObjs,
            totalCount: totalObjs,
            logs: getPhaseLogs(0, events, phase0Status, totalObjs, processedObjs),
          },
          {
            id: 'phase-semantic',
            name: '2. Semantic & Logic (Deduplication, IR Compile, AI Translate)',
            detail: 'Deduplicate metrics, compile to BI-IR AST, and translate expressions to Tableau calculations',
            status: phase1Status,
            processedCount: processedObjs,
            totalCount: totalObjs,
            logs: getPhaseLogs(1, events, phase1Status, totalObjs, processedObjs),
          },
          {
            id: 'phase-target',
            name: '3. Target Artifact Generation (Visuals, Hyper, Datasources, Staging Publish)',
            detail: 'Synthesize TDS datasources, build Hyper extracts, assemble workbooks, and publish to Tableau staging',
            status: phase2Status,
            processedCount: processedObjs,
            totalCount: totalObjs,
            logs: getPhaseLogs(2, events, phase2Status, totalObjs, processedObjs),
          },
          {
            id: 'phase-quality',
            name: '4. Quality Gates, Promotion & Report (Validation, Promote, Reconcile)',
            detail: 'Execute multi-gate validation (structural, numeric, security, visual), promote to production, reconcile, and generate report',
            status: phase3Status,
            processedCount: processedObjs,
            totalCount: totalObjs,
            logs: getPhaseLogs(3, events, phase3Status, totalObjs, processedObjs),
          },
        ];

        setTasks(dynamicTasks);
      }
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

  // Dynamic progress calculation
  const currentStage = job?.progress?.current_stage || job?.current_stage || 'DISCOVERY';
  const isComplete = ['COMPLETE', 'COMPLETE_WITH_WARNINGS', 'PUBLISHED'].includes(job?.status || '');
  const isRunning = isJobRunning(job?.status);
  const currentStageIdx = getStageIndex(currentStage);

  const progressPercent = useMemo(() => {
    if (isComplete) return 100;
    if (typeof job?.progress?.percent === 'number' && job.progress.percent > 0) {
      return Math.min(100, Math.max(0, Math.round(job.progress.percent)));
    }
    if (job?.status === 'PENDING') return 0;
    if (currentStageIdx >= 0) {
      const base = (currentStageIdx / PIPELINE_STAGE_COUNT) * 100;
      const runningBonus = isRunning ? (0.5 / PIPELINE_STAGE_COUNT) * 100 : 0;
      return Math.min(99, Math.max(5, Math.round(base + runningBonus)));
    }
    const completedStages = job?.progress?.stages_completed || [];
    if (completedStages.length > 0) {
      return Math.round((completedStages.length / PIPELINE_STAGE_COUNT) * 100);
    }
    return 0;
  }, [isComplete, job?.progress?.percent, job?.progress?.stages_completed, job?.status, currentStageIdx, isRunning]);

  // Dynamic elapsed seconds calculation
  const elapsedSeconds = useMemo(() => {
    if (typeof job?.duration_seconds === 'number' && job.duration_seconds > 0) {
      return Math.round(job.duration_seconds);
    }
    if (job?.started_at || job?.created_at) {
      const startMs = new Date(job.started_at || job.created_at).getTime();
      if (!isNaN(startMs)) {
        const endMs = job.completed_at ? new Date(job.completed_at).getTime() : currentTime;
        return Math.max(0, Math.round((endMs - startMs) / 1000));
      }
    }
    return 0;
  }, [job?.duration_seconds, job?.started_at, job?.created_at, job?.completed_at, currentTime]);

  // Dynamic stage title
  const currentStageName = useMemo(() => {
    if (isComplete) return 'Migration Completed';
    const config = getStageConfig(currentStage);
    return config?.title || currentStage;
  }, [isComplete, currentStage]);

  // Dynamic telemetry counts
  const totalObjs = job?.progress?.objects_total || job?.objects_total || 0;
  const processedObjs = job?.progress?.objects_processed || job?.objects_processed || 0;

  const parserCount = totalObjs > 0
    ? (processedObjs > 0 && processedObjs < totalObjs ? `${processedObjs}/${totalObjs} objs` : `${totalObjs} objs`)
    : undefined;

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
            <ToolChip
              label="MSTR Parser"
              active={currentStageIdx >= 0}
              count={parserCount}
            />
            <ToolChip
              label="DAG Engine"
              active={currentStageIdx >= 1 || isComplete}
            />
            <ToolChip
              label="LOD Compiler"
              active={currentStageIdx >= 4 || isComplete}
            />
            <ToolChip
              label="Hyper Builder"
              active={currentStageIdx >= 7 || isComplete}
            />
          </div>
        </div>
      </div>

      {/* ── Overall Progress ─────────────────────────────────────── */}
      <MigrationProgress
        progressPercent={progressPercent}
        currentStageName={currentStageName}
        elapsedSeconds={elapsedSeconds}
        isRunning={isRunning}
        isComplete={isComplete}
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
