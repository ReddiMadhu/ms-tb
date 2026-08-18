import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Search, ArrowRightLeft, Filter } from 'lucide-react';
import { api, type MigrationObject } from '../api';

const TYPE_COLORS: Record<string, string> = {
  metric: 'badge-primary',
  attribute: 'badge-info',
  dossier: 'badge-success',
  report: 'badge-warning',
  cube: 'badge-info',
  fact: 'badge-neutral',
  filter: 'badge-neutral',
};

const STATUS_COLORS: Record<string, string> = {
  discovered: 'badge-neutral',
  extracted: 'badge-info',
  compiled: 'badge-info',
  published: 'badge-success',
  failed: 'badge-danger',
  blocked: 'badge-danger',
  skipped: 'badge-neutral',
  reviewed: 'badge-warning',
};

function confidenceColor(c: number) {
  if (c >= 0.95) return 'var(--green)';
  if (c >= 0.80) return 'var(--primary)';
  if (c >= 0.50) return 'var(--yellow)';
  return 'var(--red)';
}

export default function ObjectsPage() {
  const { jobId } = useParams();
  const [objects, setObjects] = useState<MigrationObject[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');

  useEffect(() => {
    if (!jobId) return;
    loadObjects();
  }, [jobId]);

  async function loadObjects() {
    try {
      const res = await api.listObjects(jobId!);
      setObjects(res.objects);
    } catch (e) {
      console.error('Failed to load objects:', e);
    } finally {
      setLoading(false);
    }
  }

  const filtered = objects.filter(o => {
    if (search && !o.name.toLowerCase().includes(search.toLowerCase())) return false;
    if (typeFilter !== 'all' && o.type_name !== typeFilter) return false;
    if (statusFilter !== 'all' && o.status !== statusFilter) return false;
    return true;
  });

  const types = [...new Set(objects.map(o => o.type_name))];
  const statuses = [...new Set(objects.map(o => o.status))];

  return (
    <>
      <div className="page-header">
        <h1 className="page-title">Object Catalog</h1>
        <p className="page-subtitle">{objects.length} objects discovered</p>
      </div>

      {/* ── Summary ─────────────────────────────────────── */}
      <div className="stat-grid" style={{ marginBottom: 20 }}>
        {types.slice(0, 4).map((t, i) => (
          <motion.div
            key={t}
            className="stat-card"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.05 }}
          >
            <span className="stat-label">{t}</span>
            <span className="stat-value">{objects.filter(o => o.type_name === t).length}</span>
          </motion.div>
        ))}
      </div>

      {/* ── Filters ─────────────────────────────────────── */}
      <motion.div
        className="card"
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.15 }}
      >
        <div className="card-header" style={{ gap: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1 }}>
            <Search size={14} style={{ color: 'var(--ink-3)' }} />
            <input
              className="input"
              placeholder="Search objects…"
              value={search}
              onChange={e => setSearch(e.target.value)}
              style={{ boxShadow: 'none', background: 'transparent', padding: 0 }}
            />
          </div>
          <select
            value={typeFilter}
            onChange={e => setTypeFilter(e.target.value)}
            className="input"
            style={{ width: 130, height: 28, fontSize: 12 }}
          >
            <option value="all">All Types</option>
            {types.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
          <select
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value)}
            className="input"
            style={{ width: 130, height: 28, fontSize: 12 }}
          >
            <option value="all">All Statuses</option>
            {statuses.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>

        {loading ? (
          <div style={{ padding: 20 }}>
            {[1,2,3,4,5].map(i => (
              <div key={i} className="shimmer" style={{ height: 38, marginBottom: 6, borderRadius: 'var(--radius-sm)' }} />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <div className="empty-state">
            <ArrowRightLeft className="empty-state-icon" />
            <p className="empty-state-title">No objects match filters</p>
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Type</th>
                <th>Status</th>
                <th>Confidence</th>
                <th>Issues</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((obj, i) => (
                <motion.tr
                  key={obj.id}
                  initial={{ opacity: 0, x: -6 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: 0.2 + i * 0.02, duration: 0.3 }}
                >
                  <td>
                    <span className="table-link" style={{ cursor: 'pointer' }}>{obj.name}</span>
                    {obj.mstr_path && (
                      <span style={{ display: 'block', fontSize: 11, color: 'var(--ink-3)', marginTop: 2 }}>
                        {obj.mstr_path}
                      </span>
                    )}
                  </td>
                  <td><span className={`badge ${TYPE_COLORS[obj.type_name] || 'badge-neutral'}`}>{obj.type_name}</span></td>
                  <td><span className={`badge ${STATUS_COLORS[obj.status] || 'badge-neutral'}`}>{obj.status}</span></td>
                  <td style={{ minWidth: 130 }}>
                    <div className="confidence-meter">
                      <div className="confidence-bar">
                        <div
                          className="confidence-fill"
                          style={{
                            width: `${(obj.confidence || 0) * 100}%`,
                            background: confidenceColor(obj.confidence || 0),
                          }}
                        />
                      </div>
                      <span className="confidence-label" style={{ color: confidenceColor(obj.confidence || 0) }}>
                        {((obj.confidence || 0) * 100).toFixed(0)}%
                      </span>
                    </div>
                  </td>
                  <td className="muted" style={{ fontSize: 12 }}>
                    {(obj.blocker_count || 0) > 0 && <span style={{ color: 'var(--red)' }}>🔴 {obj.blocker_count}</span>}
                    {(obj.warning_count || 0) > 0 && <span style={{ color: 'var(--yellow)', marginLeft: 6 }}>🟡 {obj.warning_count}</span>}
                    {!(obj.blocker_count || obj.warning_count) && '—'}
                  </td>
                </motion.tr>
              ))}
            </tbody>
          </table>
        )}

        <div className="card-footer">
          <span style={{ fontSize: 12, color: 'var(--ink-3)' }}>
            Showing {filtered.length} of {objects.length} objects
          </span>
        </div>
      </motion.div>
    </>
  );
}
