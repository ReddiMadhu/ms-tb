import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  CheckCircle2, Circle, Loader2, XCircle, Clock,
  ArrowRightLeft, Eye, ShieldCheck, Pause, Play, X
} from 'lucide-react';
import { api, type Job } from '../api';

const PIPELINE_STAGES = [
  { key: 'DISCOVERY', label: 'Discovery' },
  { key: 'GRAPH', label: 'Graph Analysis' },
  { key: 'SEMANTIC', label: 'Semantic Extraction' },
  { key: 'PHYSICAL_PLAN', label: 'Physical Plan' },
  { key: 'IR_COMPILE', label: 'IR Compilation' },
  { key: 'AI_TRANSLATE', label: 'AI Translation' },
  { key: 'VISUALIZATION', label: 'Visualization' },
  { key: 'HYPER_BUILD', label: 'Hyper Build' },
  { key: 'TABLEAU_EMIT', label: 'Tableau Emit' },
  { key: 'VALIDATION', label: 'Validation' },
  { key: 'PUBLISH', label: 'Publish' },
];

function stageStatus(stage: string, current: string | undefined, jobStatus: string) {
  if (jobStatus === 'COMPLETE') return 'complete';
  if (jobStatus === 'FAILED') {
    const ci = PIPELINE_STAGES.findIndex(s => s.key === current);
    const si = PIPELINE_STAGES.findIndex(s => s.key === stage);
    if (si < ci) return 'complete';
    if (si === ci) return 'failed';
    return 'pending';
  }
  if (!current) return 'pending';
  const ci = PIPELINE_STAGES.findIndex(s => s.key === current);
  const si = PIPELINE_STAGES.findIndex(s => s.key === stage);
  if (si < ci) return 'complete';
  if (si === ci) return 'running';
  return 'pending';
}

function StageIcon({ status }: { status: string }) {
  if (status === 'complete') return <div className="pipeline-stage-icon complete"><CheckCircle2 size={12} /></div>;
  if (status === 'running') return <div className="pipeline-stage-icon running"><Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} /></div>;
  if (status === 'failed') return <div className="pipeline-stage-icon failed"><XCircle size={12} /></div>;
  return <div className="pipeline-stage-icon pending"><Circle size={8} style={{ opacity: 0.3 }} /></div>;
}

export default function JobDetailPage() {
  const { jobId } = useParams();
  const [job, setJob] = useState<Job | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!jobId) return;
    loadJob();
    const interval = setInterval(loadJob, 5000);
    return () => clearInterval(interval);
  }, [jobId]);

  async function loadJob() {
    try {
      const data = await api.getJob(jobId!);
      setJob(data);
    } catch (e) {
      console.error('Failed to load job:', e);
    } finally {
      setLoading(false);
    }
  }

  if (loading) {
    return (
      <div>
        <div className="shimmer" style={{ height: 32, width: 300, borderRadius: 'var(--radius-sm)', marginBottom: 16 }} />
        <div className="shimmer" style={{ height: 200, borderRadius: 'var(--radius-lg)' }} />
      </div>
    );
  }

  if (!job) {
    return (
      <div className="empty-state">
        <XCircle className="empty-state-icon" />
        <p className="empty-state-title">Job not found</p>
        <Link to="/" className="btn btn-secondary" style={{ marginTop: 12 }}>Back to Dashboard</Link>
      </div>
    );
  }

  const progress = job.objects_total && job.objects_processed
    ? Math.round((job.objects_processed / job.objects_total) * 100)
    : 0;

  const isRunning = !['COMPLETE', 'FAILED', 'CANCELLED'].includes(job.status);

  return (
    <>
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <h1 className="page-title">{job.name || 'Migration Job'}</h1>
          <p className="page-subtitle" style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>
            {job.id}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          {isRunning && (
            <button className="btn btn-secondary btn-sm" onClick={() => api.cancelJob(job.id)}>
              <X size={13} /> Cancel
            </button>
          )}
        </div>
      </div>

      {/* ── Stat cards ──────────────────────────────────── */}
      <div className="stat-grid">
        <motion.div className="stat-card" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0 }}>
          <span className="stat-label"><ArrowRightLeft size={14} /> Objects</span>
          <span className="stat-value">{job.objects_total || 0}</span>
          <span style={{ fontSize: 12, color: 'var(--ink-3)' }}>{job.objects_processed || 0} processed</span>
        </motion.div>
        <motion.div className="stat-card" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.06 }}>
          <span className="stat-label"><Clock size={14} /> Progress</span>
          <span className="stat-value" style={{ color: progress >= 100 ? 'var(--green)' : 'var(--primary)' }}>{progress}%</span>
          <div className="progress-bar" style={{ marginTop: 4 }}>
            <div className={`progress-bar-fill ${progress >= 100 ? 'green' : 'primary'}`} style={{ width: `${progress}%` }} />
          </div>
        </motion.div>
        <motion.div className="stat-card" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.12 }}>
          <span className="stat-label"><Eye size={14} /> Stage</span>
          <span className="stat-value" style={{ fontSize: 18 }}>{job.current_stage || 'PENDING'}</span>
        </motion.div>
        <motion.div className="stat-card" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.18 }}>
          <span className="stat-label"><ShieldCheck size={14} /> Status</span>
          <span className="stat-value" style={{
            fontSize: 18,
            color: job.status === 'COMPLETE' ? 'var(--green)' : job.status === 'FAILED' ? 'var(--red)' : 'var(--primary)',
          }}>{job.status}</span>
        </motion.div>
      </div>

      {/* ── Pipeline stages ─────────────────────────────── */}
      <motion.div
        className="card"
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2, duration: 0.5, ease: [0.23, 1, 0.32, 1] }}
      >
        <div className="card-header">
          <span className="card-title">Pipeline Stages</span>
          {isRunning && <span className="badge badge-primary" style={{ animation: 'fade-in 0.5s ease' }}>Live</span>}
        </div>
        <div style={{ padding: '12px 4px' }}>
          <div className="pipeline-stages">
            {PIPELINE_STAGES.map((stage, i) => {
              const status = stageStatus(stage.key, job.current_stage, job.status);
              return (
                <motion.div
                  key={stage.key}
                  className={`pipeline-stage ${status}`}
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: 0.25 + i * 0.03, duration: 0.35, ease: [0.23, 1, 0.32, 1] }}
                >
                  <StageIcon status={status} />
                  <span className="pipeline-stage-name">{stage.label}</span>
                  {status === 'complete' && <span className="pipeline-stage-duration">✓</span>}
                  {status === 'running' && <span className="pipeline-stage-duration" style={{ color: 'var(--primary)' }}>in progress…</span>}
                </motion.div>
              );
            })}
          </div>
        </div>
      </motion.div>

      {/* ── Quick links ─────────────────────────────────── */}
      <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
        <Link to={`/jobs/${job.id}/objects`} className="btn btn-secondary">
          <ArrowRightLeft size={14} /> View Objects
        </Link>
        <Link to={`/jobs/${job.id}/review`} className="btn btn-secondary">
          <Eye size={14} /> Review Queue
        </Link>
        <Link to={`/jobs/${job.id}/validation`} className="btn btn-secondary">
          <ShieldCheck size={14} /> Validation
        </Link>
      </div>

      {/* ── Error message ───────────────────────────────── */}
      {job.error_message && (
        <motion.div
          className="card card-pad"
          style={{ marginTop: 16, borderLeft: '3px solid var(--red)' }}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
        >
          <p style={{ fontSize: 13, fontWeight: 600, color: 'var(--red)', marginBottom: 4 }}>Error</p>
          <pre className="code-block" style={{ fontSize: 12 }}>{job.error_message}</pre>
        </motion.div>
      )}
    </>
  );
}
