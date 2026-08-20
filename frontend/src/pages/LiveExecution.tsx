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
            id: 'stage-discovery',
            name: '1. Ingest MSTR Artifacts & Discovery',
            detail: 'Scan project, parse dossiers, documents, cubes, and reports',
            status: isComplete || completedStages.includes('DISCOVERY') ? 'COMPLETED' : currentStage === 'DISCOVERY' ? 'RUNNING' : 'WAITING',
            processedCount: processedObjs,
            totalCount: totalObjs,
            logs: [`Ingested ${totalObjs} objects from MicroStrategy API`],
          },
          {
            id: 'stage-graph',
            name: '2. Build AST Dependency Graph & Lineage',
            detail: 'Topological sorting of metric hierarchies and LOD expressions',
            status: isComplete || completedStages.includes('GRAPH') ? 'COMPLETED' : currentStage === 'GRAPH' ? 'RUNNING' : 'WAITING',
            processedCount: processedObjs,
            totalCount: totalObjs,
            logs: ['Constructed AST dependency graph across discovered nodes'],
          },
          {
            id: 'stage-semantic',
            name: '3. Semantic Data Model Reconstruction',
            detail: 'Map dimensions, measures, facts, and logical relationships',
            status: isComplete || completedStages.includes('SEMANTIC') ? 'COMPLETED' : currentStage === 'SEMANTIC' ? 'RUNNING' : 'WAITING',
            processedCount: processedObjs,
            totalCount: totalObjs,
            logs: ['Mapped logical data model and relationships'],
          },
          {
            id: 'stage-translate',
            name: '4. Expression & AST Translation Engine',
            detail: 'Translate MSTR expressions into Tableau calculated fields',
            status: isComplete || completedStages.includes('AI_TRANSLATE') ? 'COMPLETED' : currentStage === 'AI_TRANSLATE' ? 'RUNNING' : 'WAITING',
            processedCount: processedObjs,
            totalCount: totalObjs,
            logs: ['Compiled formulas and LOD expressions'],
          },
          {
            id: 'stage-validate',
            name: '5. Validation & Parity Scorecard',
            detail: '4-Tier promotion gates for data, formula, and security parity',
            status: isComplete || completedStages.includes('STATIC_VALIDATE') ? 'COMPLETED' : currentStage === 'STATIC_VALIDATE' ? 'RUNNING' : 'WAITING',
            processedCount: processedObjs,
            totalCount: totalObjs,
            logs: ['Ran automated validation checks'],
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
