import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { motion } from 'framer-motion';
import { ShieldCheck, CheckCircle2, XCircle, AlertTriangle } from 'lucide-react';
import { api, type ValidationResult } from '../api';

function gateColor(value: number, threshold: number) {
  if (value >= threshold) return 'pass';
  if (value >= threshold * 0.95) return 'warn';
  return 'fail';
}

export default function ValidationPage() {
  const { jobId } = useParams();
  const [result, setResult] = useState<ValidationResult | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!jobId) return;
    loadValidation();
  }, [jobId]);

  async function loadValidation() {
    try {
      const data = await api.getValidation(jobId!);
      setResult(data);
    } catch (e) {
      console.error('Failed to load validation:', e);
    } finally {
      setLoading(false);
    }
  }

  if (loading) {
    return (
      <div>
        <div className="shimmer" style={{ height: 32, width: 280, borderRadius: 'var(--radius-sm)', marginBottom: 16 }} />
        <div className="scorecard-grid">
          {[1,2,3,4].map(i => <div key={i} className="shimmer" style={{ height: 120, borderRadius: 'var(--radius-lg)' }} />)}
        </div>
      </div>
    );
  }

  if (!result) {
    return (
      <div className="empty-state">
        <ShieldCheck className="empty-state-icon" />
        <p className="empty-state-title">No validation data available</p>
        <p className="empty-state-desc">Validation runs automatically after the Tableau emission stage.</p>
      </div>
    );
  }

  const gates = [
    { name: 'Structural', value: result.structural_confidence || 0, threshold: 0.99, icon: '🏗️' },
    { name: 'Financial KPI', value: result.financial_kpi_confidence || 0, threshold: 0.98, icon: '💰' },
    { name: 'Security', value: result.security_confidence || 0, threshold: 1.0, icon: '🔒' },
    { name: 'Visual', value: result.visual_confidence || 0, threshold: 0.80, icon: '👁️' },
  ];

  return (
    <>
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <h1 className="page-title">Validation Scorecard</h1>
          <p className="page-subtitle">Multi-gate quality assurance results</p>
        </div>
        <div className={`badge ${result.auto_publish_ok ? 'badge-success' : 'badge-danger'}`} style={{ height: 28, fontSize: 12, padding: '0 12px' }}>
          {result.auto_publish_ok ? (
            <><CheckCircle2 size={13} style={{ marginRight: 4 }} /> Auto-Publish Ready</>
          ) : (
            <><XCircle size={13} style={{ marginRight: 4 }} /> Review Required</>
          )}
        </div>
      </div>

      {/* ── Scorecard gates ─────────────────────────────── */}
      <div className="scorecard-grid" style={{ marginBottom: 24 }}>
        {gates.map((gate, i) => (
          <motion.div
            key={gate.name}
            className="scorecard-item"
            initial={{ opacity: 0, scale: 0.92 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: i * 0.08, duration: 0.4, ease: [0.23, 1, 0.32, 1] }}
          >
            <div className="scorecard-gate">
              <span style={{ marginRight: 4 }}>{gate.icon}</span>
              {gate.name}
            </div>
            <div className={`scorecard-value ${gateColor(gate.value, gate.threshold)}`}>
              {(gate.value * 100).toFixed(1)}%
            </div>
            <div className="scorecard-threshold">
              threshold: {(gate.threshold * 100).toFixed(0)}%
            </div>
            <div className="progress-bar" style={{ marginTop: 8 }}>
              <div
                className={`progress-bar-fill ${gate.value >= gate.threshold ? 'green' : gate.value >= gate.threshold * 0.95 ? 'yellow' : 'red'}`}
                style={{ width: `${gate.value * 100}%` }}
              />
            </div>
          </motion.div>
        ))}
      </div>

      {/* ── Issue summary ───────────────────────────────── */}
      <div className="stat-grid">
        <motion.div className="stat-card" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }}>
          <span className="stat-label"><XCircle size={14} style={{ color: 'var(--red)' }} /> Blockers</span>
          <span className="stat-value" style={{ color: (result.blocker_count || 0) > 0 ? 'var(--red)' : 'var(--green)' }}>
            {result.blocker_count || 0}
          </span>
        </motion.div>
        <motion.div className="stat-card" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.36 }}>
          <span className="stat-label"><AlertTriangle size={14} style={{ color: 'var(--yellow)' }} /> Warnings</span>
          <span className="stat-value">{result.warning_count || 0}</span>
        </motion.div>
      </div>

      {/* ── Check details ───────────────────────────────── */}
      {result.checks && result.checks.length > 0 && (
        <motion.div
          className="card"
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.4 }}
          style={{ marginTop: 24 }}
        >
          <div className="card-header">
            <span className="card-title">Validation Checks</span>
            <span style={{ fontSize: 12, color: 'var(--ink-3)' }}>{result.checks.length} checks</span>
          </div>
          <table className="data-table">
            <thead>
              <tr>
                <th>Status</th>
                <th>Check</th>
                <th>Category</th>
                <th>Message</th>
              </tr>
            </thead>
            <tbody>
              {result.checks.map((check, i) => (
                <motion.tr
                  key={i}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: 0.45 + i * 0.02 }}
                >
                  <td>
                    {check.passed ? (
                      <CheckCircle2 size={15} style={{ color: 'var(--green)' }} />
                    ) : (
                      <XCircle size={15} style={{ color: 'var(--red)' }} />
                    )}
                  </td>
                  <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{check.check_type}</td>
                  <td><span className={`badge ${check.category === 'security' ? 'badge-danger' : check.category === 'financial_kpi' ? 'badge-warning' : 'badge-info'}`}>{check.category}</span></td>
                  <td className="muted" style={{ fontSize: 12 }}>{check.message}</td>
                </motion.tr>
              ))}
            </tbody>
          </table>
        </motion.div>
      )}
    </>
  );
}
