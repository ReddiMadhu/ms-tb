import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Eye, CheckCircle2, XCircle, AlertTriangle, ChevronDown, ChevronUp } from 'lucide-react';
import { api, type ReviewTask } from '../api';

export default function ReviewQueuePage() {
  const { jobId } = useParams();
  const [tasks, setTasks] = useState<ReviewTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    loadTasks();
  }, [jobId]);

  async function loadTasks() {
    try {
      const res = await api.listReviewTasks();
      setTasks(jobId ? res.tasks.filter(t => t.job_id === jobId) : res.tasks);
    } catch (e) {
      console.error('Failed to load review tasks:', e);
    } finally {
      setLoading(false);
    }
  }

  async function handleApprove(taskId: string) {
    try {
      await api.approveReview(taskId, { notes: 'Approved via UI' });
      loadTasks();
    } catch (e) {
      console.error('Approve failed:', e);
    }
  }

  const pending = tasks.filter(t => t.status === 'pending');
  const blockers = pending.filter(t => t.severity === 'blocker');
  const warnings = pending.filter(t => t.severity === 'warning');

  return (
    <>
      <div className="page-header">
        <h1 className="page-title">Review Queue</h1>
        <p className="page-subtitle">Objects requiring human review before publication</p>
      </div>

      {/* ── Summary cards ───────────────────────────────── */}
      <div className="stat-grid">
        <motion.div className="stat-card" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0 }}>
          <span className="stat-label"><Eye size={14} /> Pending</span>
          <span className="stat-value">{pending.length}</span>
        </motion.div>
        <motion.div className="stat-card" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.06 }}>
          <span className="stat-label"><XCircle size={14} style={{ color: 'var(--red)' }} /> Blockers</span>
          <span className="stat-value" style={{ color: blockers.length > 0 ? 'var(--red)' : undefined }}>{blockers.length}</span>
        </motion.div>
        <motion.div className="stat-card" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.12 }}>
          <span className="stat-label"><AlertTriangle size={14} style={{ color: 'var(--yellow)' }} /> Warnings</span>
          <span className="stat-value" style={{ color: warnings.length > 0 ? 'var(--yellow)' : undefined }}>{warnings.length}</span>
        </motion.div>
        <motion.div className="stat-card" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.18 }}>
          <span className="stat-label"><CheckCircle2 size={14} style={{ color: 'var(--green)' }} /> Resolved</span>
          <span className="stat-value" style={{ color: 'var(--green)' }}>
            {tasks.filter(t => t.status === 'approved' || t.status === 'rejected').length}
          </span>
        </motion.div>
      </div>

      {/* ── Task list ───────────────────────────────────── */}
      <motion.div
        className="card"
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
      >
        <div className="card-header">
          <span className="card-title">Review Tasks</span>
        </div>

        {loading ? (
          <div style={{ padding: 20 }}>
            {[1,2,3].map(i => (
              <div key={i} className="shimmer" style={{ height: 52, marginBottom: 8, borderRadius: 'var(--radius-sm)' }} />
            ))}
          </div>
        ) : tasks.length === 0 ? (
          <div className="empty-state">
            <CheckCircle2 className="empty-state-icon" style={{ color: 'var(--green)' }} />
            <p className="empty-state-title">No items to review</p>
            <p className="empty-state-desc">All objects passed automated validation.</p>
          </div>
        ) : (
          <div>
            {tasks.map((task, i) => (
              <motion.div
                key={task.id}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.25 + i * 0.03 }}
                style={{ borderBottom: '1px solid var(--line)' }}
              >
                <div
                  style={{
                    display: 'flex', alignItems: 'center', gap: 12,
                    padding: '12px 20px', cursor: 'pointer',
                    transition: 'background 100ms',
                  }}
                  onClick={() => setExpandedId(expandedId === task.id ? null : task.id)}
                  onMouseEnter={e => (e.currentTarget.style.background = 'var(--hover)')}
                  onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                >
                  {task.severity === 'blocker' ? (
                    <XCircle size={16} style={{ color: 'var(--red)', flexShrink: 0 }} />
                  ) : (
                    <AlertTriangle size={16} style={{ color: 'var(--yellow)', flexShrink: 0 }} />
                  )}

                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--ink)' }}>
                      {task.object_id}
                    </div>
                    <div style={{ fontSize: 12, color: 'var(--ink-3)', marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {task.reason}
                    </div>
                  </div>

                  <span className={`badge ${task.status === 'pending' ? 'badge-warning' : task.status === 'approved' ? 'badge-success' : 'badge-neutral'}`}>
                    {task.status}
                  </span>

                  <span className="confidence-label" style={{ color: (task.confidence || 0) >= 0.85 ? 'var(--green)' : 'var(--yellow)' }}>
                    {((task.confidence || 0) * 100).toFixed(0)}%
                  </span>

                  {expandedId === task.id ? <ChevronUp size={14} style={{ color: 'var(--ink-3)' }} /> : <ChevronDown size={14} style={{ color: 'var(--ink-3)' }} />}
                </div>

                {/* ── Expanded detail ────────────────────── */}
                {expandedId === task.id && (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: 'auto' }}
                    exit={{ opacity: 0, height: 0 }}
                    style={{ padding: '0 20px 16px', overflow: 'hidden' }}
                  >
                    {(task.mstr_expression || task.generated_calc) && (
                      <div className="side-by-side" style={{ marginBottom: 12 }}>
                        <div className="side-by-side-panel">
                          <div className="side-by-side-label">MSTR Expression</div>
                          <pre className="code-block" style={{ margin: 0, fontSize: 12 }}>
                            {task.mstr_expression || 'N/A'}
                          </pre>
                        </div>
                        <div className="side-by-side-panel">
                          <div className="side-by-side-label">Generated Tableau Calc</div>
                          <pre className="code-block" style={{ margin: 0, fontSize: 12 }}>
                            {task.generated_calc || 'N/A'}
                          </pre>
                        </div>
                      </div>
                    )}

                    <div style={{ display: 'flex', gap: 6 }}>
                      {task.status === 'pending' && (
                        <>
                          <button className="btn btn-primary btn-sm" onClick={() => handleApprove(task.id)}>
                            <CheckCircle2 size={12} /> Approve
                          </button>
                          <button className="btn btn-secondary btn-sm">
                            <XCircle size={12} /> Reject
                          </button>
                        </>
                      )}
                    </div>
                  </motion.div>
                )}
              </motion.div>
            ))}
          </div>
        )}
      </motion.div>
    </>
  );
}
