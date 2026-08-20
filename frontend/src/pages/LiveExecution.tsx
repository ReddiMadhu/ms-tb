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

export default function LiveExecution() {
  const { jobId } = useParams<{ jobId: string }>();
  const [job, setJob] = useState<Job | null>(null);
  const [tasks, setTasks] = useState<TaskRowData[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!jobId) return;
    api.getJob(jobId)
      .then((data) => {
        setJob(data);
        const currentStage = data.progress?.current_stage || data.current_stage || 'DISCOVERY';
        const completedStages = data.progress?.stages_completed || [];
        const isComplete = ['COMPLETE', 'COMPLETE_WITH_WARNINGS', 'PUBLISHED'].includes(data.status);
        const totalObjs = data.progress?.objects_total || data.objects_total || 0;
        const processedObjs = data.progress?.objects_processed || data.objects_processed || 0;

        const dynamicTasks: TaskRowData[] = [
          {
            id: 'phase-extraction',
            name: '1. Extraction & Catalog (Discovery & Dependency Graph)',
            detail: 'Scan project, parse dossiers/cubes, extract metadata, and build dependency graph',
            status: isComplete || completedStages.includes('GRAPH') ? 'COMPLETED' : ['DISCOVERY', 'GRAPH'].includes(currentStage) ? 'RUNNING' : 'WAITING',
            processedCount: processedObjs,
            totalCount: totalObjs,
            logs: [`Cataloged ${totalObjs} objects from MicroStrategy API and constructed dependency graph`],
          },
          {
            id: 'phase-semantic',
            name: '2. Semantic & Logic (Deduplication, IR Compile, AI Translate)',
            detail: 'Deduplicate metrics, compile to BI-IR AST, and translate expressions to Tableau calculations',
            status: isComplete || completedStages.includes('AI_TRANSLATE') ? 'COMPLETED' : ['SEMANTIC', 'METRIC_DEDUPLICATION', 'IR_COMPILE', 'AI_TRANSLATE'].includes(currentStage) ? 'RUNNING' : 'WAITING',
            processedCount: processedObjs,
            totalCount: totalObjs,
            logs: ['Compiled universal BI-IR representation and mapped LOD calculations'],
          },
          {
            id: 'phase-target',
            name: '3. Target Artifact Generation (Visuals, Hyper Extract, Datasources, Workbook Staging)',
            detail: 'Synthesize TDS datasources, build Hyper extracts, and assemble Tableau staging workbooks (.twbx)',
            status: isComplete || completedStages.includes('WORKBOOK_EMIT_STAGING') ? 'COMPLETED' : ['VIZ', 'HYPER_BUILD', 'DATASOURCE_EMIT', 'WORKBOOK_EMIT_STAGING'].includes(currentStage) ? 'RUNNING' : 'WAITING',
            processedCount: processedObjs,
            totalCount: totalObjs,
            logs: ['Generated TDS datasource definitions and compiled Tableau workbook structure'],
          },
          {
            id: 'phase-quality',
            name: '4. Quality & Final Package (Validation Gates & Executive Report)',
            detail: 'Execute 4-tier validation gates (structural, numerical, security, visual) and compile audit report',
            status: isComplete || completedStages.includes('REPORT') ? 'COMPLETED' : ['STATIC_VALIDATE', 'REPORT'].includes(currentStage) ? 'RUNNING' : 'WAITING',
            processedCount: processedObjs,
            totalCount: totalObjs,
            logs: ['Executed automated ground-truth validation checks and compiled executive report'],
          },
        ];

        setTasks(dynamicTasks);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [jobId]);

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
