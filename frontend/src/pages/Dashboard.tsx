import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  Plus, Activity, CheckCircle2, AlertTriangle, Zap,
  ArrowUpRight, RefreshCw, Layers, Sparkles
} from 'lucide-react';
import { api, type Job } from '../api';

const STATUS_BADGE: Record<string, { cls: string; label: string }> = {
  PENDING: { cls: 'badge-neutral', label: 'Pending' },
  RUNNING: { cls: 'badge-info', label: 'Running' },
  DISCOVERY: { cls: 'badge-info', label: 'Discovery' },
  GRAPH: { cls: 'badge-info', label: 'Graph' },
  SEMANTIC: { cls: 'badge-info', label: 'Semantic' },
  COMPLETE: { cls: 'badge-success', label: 'Complete' },
  FAILED: { cls: 'badge-danger', label: 'Failed' },
  CANCELLED: { cls: 'badge-neutral', label: 'Cancelled' },
};

function getStatusBadge(status: string) {
  return STATUS_BADGE[status] || STATUS_BADGE['RUNNING'] || { cls: 'badge-info', label: status };
}

function timeAgo(date: string) {
  const d = new Date(date);
  const now = new Date();
  const diff = Math.floor((now.getTime() - d.getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export default function DashboardPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    loadJobs();
    const interval = setInterval(loadJobs, 10_000);
    return () => clearInterval(interval);
  }, []);

  async function loadJobs(showRefreshing = false) {
    if (showRefreshing) setRefreshing(true);
    try {
      const res = await api.listJobs();
      setJobs(res.jobs || []);
    } catch (e) {
      console.error('Failed to load jobs:', e);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  const stats = {
    total: jobs.length,
    active: jobs.filter(j => !['COMPLETE', 'FAILED', 'CANCELLED'].includes(j.status)).length,
    complete: jobs.filter(j => j.status === 'COMPLETE').length,
    failed: jobs.filter(j => j.status === 'FAILED').length,
  };

  return (
    <>
      <div className="page-header-gradient">
        <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <h1 className="page-title">Migration Dashboard</h1>
            <p className="page-subtitle">Enterprise MicroStrategy to Tableau Server & Cloud pipeline orchestrator</p>
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            <button
              type="button"
              className="btn btn-secondary btn-icon"
              onClick={() => loadJobs(true)}
              title="Refresh jobs"
            >
              <RefreshCw size={14} className={refreshing ? 'spinner' : ''} />
            </button>
            <Link to="/jobs/new" className="btn btn-primary">
              <Plus size={15} />
              New Migration Job
            </Link>
          </div>
        </div>

        {/* ── Stat cards ──────────────────────────────────── */}
        <div className="stat-grid">
          <motion.div
            className="stat-card"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0, duration: 0.4, ease: [0.23, 1, 0.32, 1] }}
          >
            <span className="stat-label"><Activity size={14} /> Total Jobs</span>
            <span className="stat-value">{stats.total}</span>
          </motion.div>
          <motion.div
            className="stat-card"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.06, duration: 0.4, ease: [0.23, 1, 0.32, 1] }}
          >
            <span className="stat-label"><Zap size={14} /> Active In-Flight</span>
            <span className="stat-value" style={{ color: stats.active > 0 ? 'var(--primary)' : undefined }}>
              {stats.active}
            </span>
          </motion.div>
          <motion.div
            className="stat-card"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.12, duration: 0.4, ease: [0.23, 1, 0.32, 1] }}
          >
            <span className="stat-label"><CheckCircle2 size={14} /> Complete & Verified</span>
            <span className="stat-value" style={{ color: stats.complete > 0 ? 'var(--green)' : undefined }}>
              {stats.complete}
            </span>
          </motion.div>
          <motion.div
            className="stat-card"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.18, duration: 0.4, ease: [0.23, 1, 0.32, 1] }}
          >
            <span className="stat-label"><AlertTriangle size={14} /> Needs Attention</span>
            <span className="stat-value" style={{ color: stats.failed > 0 ? 'var(--red)' : undefined }}>
              {stats.failed}
            </span>
          </motion.div>
        </div>
      </div>

      {/* ── Jobs table ──────────────────────────────────── */}
      <motion.div
        className="card"
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2, duration: 0.5, ease: [0.23, 1, 0.32, 1] }}
      >
        <div className="card-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Layers size={15} style={{ color: 'var(--primary)' }} />
            <span className="card-title">Recent Migration Jobs</span>
          </div>
          <span style={{ fontSize: 12, color: 'var(--ink-3)', fontFamily: 'var(--font-mono)' }}>
            {jobs.length} total
          </span>
        </div>

        {loading ? (
          <div style={{ padding: 20 }}>
            {[1, 2, 3].map(i => (
              <div key={i} className="shimmer" style={{ height: 44, marginBottom: 10, borderRadius: 'var(--radius-sm)' }} />
            ))}
          </div>
        ) : jobs.length === 0 ? (
          <div className="empty-state">
            <Zap className="empty-state-icon" />
            <p className="empty-state-title">No migration jobs yet</p>
            <p className="empty-state-desc">
              Connect your MicroStrategy environment, scan dossiers, and start your first automated migration pipeline.
            </p>
            <Link to="/jobs/new" className="btn btn-primary" style={{ marginTop: 20 }}>
              <Plus size={15} /> Create First Migration Job
            </Link>
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Job Name</th>
                  <th>Status</th>
                  <th>Stage</th>
                  <th>Progress</th>
                  <th>Created</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((job, i) => {
                  const badge = getStatusBadge(job.status);
                  const progress = job.objects_total && job.objects_processed
                    ? Math.round((job.objects_processed / job.objects_total) * 100)
                    : (job.status === 'COMPLETE' ? 100 : 0);

                  return (
                    <motion.tr
                      key={job.id}
                      initial={{ opacity: 0, x: -8 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: 0.2 + i * 0.03, duration: 0.35, ease: [0.23, 1, 0.32, 1] }}
                    >
                      <td>
                        <Link to={`/jobs/${job.id}`} className="table-link" style={{ fontWeight: 600 }}>
                          {job.name}
                        </Link>
                        <div style={{ fontSize: 11, color: 'var(--ink-3)', marginTop: 2 }}>
                          Project: {job.mstr_project_id.slice(0, 12)}...
                        </div>
                      </td>
                      <td>
                        <span className={`badge ${badge.cls}`}>{badge.label}</span>
                      </td>
                      <td className="muted" style={{ fontSize: 12 }}>
                        {job.current_stage || '—'}
                      </td>
                      <td style={{ minWidth: 140 }}>
                        <div className="confidence-meter">
                          <div className="confidence-bar">
                            <div
                              className={`confidence-fill ${job.status === 'COMPLETE' ? 'green' : 'primary'}`}
                              style={{ width: `${progress}%` }}
                            />
                          </div>
                          <span className="confidence-label">{progress}%</span>
                        </div>
                      </td>
                      <td className="muted" style={{ fontSize: 12 }}>
                        {timeAgo(job.created_at)}
                      </td>
                      <td>
                        <Link to={`/jobs/${job.id}`} className="btn btn-ghost btn-sm btn-icon" title="View Job Details">
                          <ArrowUpRight size={15} />
                        </Link>
                      </td>
                    </motion.tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </motion.div>
    </>
  );
}
