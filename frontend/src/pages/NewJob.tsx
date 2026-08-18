import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Rocket, Search, Database, Server, ChevronRight, CheckCircle2,
  Sliders, ShieldCheck
} from 'lucide-react';
import { api } from '../api';

const STEPS = ['Connection & Credentials', 'Dossiers Selection', 'Configure & Launch'];

interface FormState {
  name: string;
  mstr_base_url: string;
  mstr_username: string;
  mstr_password: string;
  mstr_project_id: string;
  tableau_server_url: string;
  tableau_site_id: string;
  tableau_target_project: string;
  auto_publish: boolean;
  numeric_threshold: number;
}

export default function NewJobPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [loading, setLoading] = useState(false);
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const [apiError, setApiError] = useState<string | null>(null);

  const [form, setForm] = useState<FormState>({
    name: '',
    mstr_base_url: '',
    mstr_username: '',
    mstr_password: '',
    mstr_project_id: '',
    tableau_server_url: '',
    tableau_site_id: 'default',
    tableau_target_project: 'Migrated Dashboards',
    auto_publish: true,
    numeric_threshold: 0.98,
  });

  // Only MSTR source fields are mandatory — Tableau target is optional (download-only mode)
  const errors = {
    name: !form.name.trim() ? 'Job Name is required' : null,
    mstr_base_url: !form.mstr_base_url.trim() ? 'MSTR Server URL is required' : null,
    mstr_username: !form.mstr_username.trim() ? 'MSTR Username is required' : null,
    mstr_password: !form.mstr_password ? 'MSTR Password is required' : null,
    mstr_project_id: !form.mstr_project_id.trim() ? 'MSTR Project ID is required' : null,
  };

  const isStep0Valid = !errors.name && !errors.mstr_base_url && !errors.mstr_username &&
    !errors.mstr_password && !errors.mstr_project_id;

  const hasTableauTarget = !!form.tableau_server_url.trim();

  const handleBlur = (field: string) => {
    setTouched(prev => ({ ...prev, [field]: true }));
  };

  const handleNextFromConnection = () => {
    // Touch only mandatory MSTR source fields
    setTouched({
      name: true,
      mstr_base_url: true,
      mstr_username: true,
      mstr_password: true,
      mstr_project_id: true,
    });

    if (isStep0Valid) {
      setStep(1);
    }
  };

  async function handleSubmit() {
    setLoading(true);
    setApiError(null);
    try {
      const job = await api.createJob({
        name: form.name,
        mstr_base_url: form.mstr_base_url,
        mstr_username: form.mstr_username,
        mstr_password: form.mstr_password,
        mstr_project_id: form.mstr_project_id,
        tableau_server_url: form.tableau_server_url,
        tableau_site_id: form.tableau_site_id,
        tableau_target_project: form.tableau_target_project,
        auto_publish: form.auto_publish,
        numeric_threshold: form.numeric_threshold,
      });
      navigate(`/jobs/${job.id}`);
    } catch (e: any) {
      console.error('Create job failed:', e);
      setApiError(e?.message || 'Failed to create job');
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <div className="page-header">
        <h1 className="page-title">New Migration Job</h1>
        <p className="page-subtitle">Configure source & target connections with verified credentials</p>
      </div>

      {/* ── Step indicator ──────────────────────────────── */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 28 }}>
        {STEPS.map((s, i) => (
          <button
            key={s}
            onClick={() => {
              if (i === 0 || isStep0Valid) setStep(i);
            }}
            style={{
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '6px 14px',
              borderRadius: 'var(--radius-full)',
              border: 'none',
              cursor: (i === 0 || isStep0Valid) ? 'pointer' : 'not-allowed',
              opacity: (i > 0 && !isStep0Valid) ? 0.6 : 1,
              fontSize: 13, fontWeight: 500,
              background: i === step ? 'var(--primary)' : 'var(--field)',
              color: i === step ? 'white' : 'var(--ink-2)',
              boxShadow: i === step ? '0 2px 8px rgba(251,78,11,0.3)' : 'var(--shadow-btn)',
              transition: 'all 200ms ease',
              fontFamily: 'var(--font-sans)',
            }}
          >
            {i < step ? <CheckCircle2 size={13} /> : <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>{String(i+1).padStart(2,'0')}</span>}
            {s}
          </button>
        ))}
      </div>

      {/* ── Step 1: Mandatory Connection Entries ────────────────── */}
      {step === 0 && (
        <motion.div
          className="card card-pad"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, ease: [0.23,1,0.32,1] }}
        >
          <div style={{ display: 'grid', gap: 20, maxWidth: 640 }}>
            {/* Job Metadata */}
            <div className="input-group">
              <label className="input-label" style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span>Job Name <span style={{ color: 'var(--primary)' }}>*</span></span>
                {touched.name && errors.name && (
                  <span style={{ color: 'var(--red)', fontSize: 11 }}>{errors.name}</span>
                )}
              </label>
              <input
                className="input"
                placeholder="e.g. Q3 2026 Sales Analytics Migration"
                value={form.name}
                onBlur={() => handleBlur('name')}
                onChange={e => setForm({ ...form, name: e.target.value })}
                style={{
                  boxShadow: touched.name && errors.name ? '0 0 0 1px var(--red)' : undefined,
                }}
              />
            </div>

            {/* MSTR Source Section */}
            <div style={{ borderTop: '1px solid var(--line)', paddingTop: 16 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
                <Database size={15} style={{ color: 'var(--primary)' }} />
                <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--ink)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  MicroStrategy Source (Mandatory)
                </span>
              </div>

              <div style={{ display: 'grid', gap: 14 }}>
                <div className="input-group">
                  <label className="input-label" style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span>Library REST API URL <span style={{ color: 'var(--primary)' }}>*</span></span>
                    {touched.mstr_base_url && errors.mstr_base_url && (
                      <span style={{ color: 'var(--red)', fontSize: 11 }}>{errors.mstr_base_url}</span>
                    )}
                  </label>
                  <input
                    className="input"
                    placeholder="https://mstr.company.com/MicroStrategyLibrary"
                    value={form.mstr_base_url}
                    onBlur={() => handleBlur('mstr_base_url')}
                    onChange={e => setForm({ ...form, mstr_base_url: e.target.value })}
                    style={{
                      boxShadow: touched.mstr_base_url && errors.mstr_base_url ? '0 0 0 1px var(--red)' : undefined,
                    }}
                  />
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                  <div className="input-group">
                    <label className="input-label" style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span>MSTR Username <span style={{ color: 'var(--primary)' }}>*</span></span>
                      {touched.mstr_username && errors.mstr_username && (
                        <span style={{ color: 'var(--red)', fontSize: 11 }}>{errors.mstr_username}</span>
                      )}
                    </label>
                    <input
                      className="input"
                      placeholder="e.g. administrator"
                      value={form.mstr_username}
                      onBlur={() => handleBlur('mstr_username')}
                      onChange={e => setForm({ ...form, mstr_username: e.target.value })}
                      style={{
                        boxShadow: touched.mstr_username && errors.mstr_username ? '0 0 0 1px var(--red)' : undefined,
                      }}
                    />
                  </div>
                  <div className="input-group">
                    <label className="input-label" style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span>MSTR Password <span style={{ color: 'var(--primary)' }}>*</span></span>
                      {touched.mstr_password && errors.mstr_password && (
                        <span style={{ color: 'var(--red)', fontSize: 11 }}>{errors.mstr_password}</span>
                      )}
                    </label>
                    <input
                      className="input"
                      type="password"
                      placeholder="••••••••••••"
                      value={form.mstr_password}
                      onBlur={() => handleBlur('mstr_password')}
                      onChange={e => setForm({ ...form, mstr_password: e.target.value })}
                      style={{
                        boxShadow: touched.mstr_password && errors.mstr_password ? '0 0 0 1px var(--red)' : undefined,
                      }}
                    />
                  </div>
                </div>

                <div className="input-group">
                  <label className="input-label" style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span>MSTR Project ID (GUID) <span style={{ color: 'var(--primary)' }}>*</span></span>
                    {touched.mstr_project_id && errors.mstr_project_id && (
                      <span style={{ color: 'var(--red)', fontSize: 11 }}>{errors.mstr_project_id}</span>
                    )}
                  </label>
                  <input
                    className="input"
                    style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}
                    placeholder="B7CA92F04B9FAE8D941C3E9B7E0CD754"
                    value={form.mstr_project_id}
                    onBlur={() => handleBlur('mstr_project_id')}
                    onChange={e => setForm({ ...form, mstr_project_id: e.target.value })}
                    style={{
                      boxShadow: touched.mstr_project_id && errors.mstr_project_id ? '0 0 0 1px var(--red)' : undefined,
                    }}
                  />
                </div>
              </div>
            </div>

            {/* Tableau Target Section — OPTIONAL */}
            <div style={{ borderTop: '1px solid var(--line)', paddingTop: 16 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Server size={15} style={{ color: hasTableauTarget ? 'var(--primary)' : 'var(--ink-3)' }} />
                  <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--ink)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    Tableau Target
                  </span>
                  <span className={`badge ${hasTableauTarget ? 'badge-success' : 'badge-neutral'}`}>
                    {hasTableauTarget ? 'Connected' : 'Optional'}
                  </span>
                </div>
              </div>

              <div style={{ display: 'grid', gap: 14 }}>
                <div className="input-group">
                  <label className="input-label">Tableau Server / Cloud URL</label>
                  <input
                    className="input"
                    placeholder="https://tableau.company.com"
                    value={form.tableau_server_url}
                    onChange={e => setForm({ ...form, tableau_server_url: e.target.value })}
                  />
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                  <div className="input-group">
                    <label className="input-label">Site ID</label>
                    <input
                      className="input"
                      placeholder="default"
                      value={form.tableau_site_id}
                      onChange={e => setForm({ ...form, tableau_site_id: e.target.value })}
                    />
                  </div>
                  <div className="input-group">
                    <label className="input-label">Target Project</label>
                    <input
                      className="input"
                      placeholder="Migrated Dashboards"
                      value={form.tableau_target_project}
                      onChange={e => setForm({ ...form, tableau_target_project: e.target.value })}
                    />
                  </div>
                </div>
              </div>
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', paddingTop: 8 }}>
              <button
                type="button"
                className="btn btn-primary"
                onClick={handleNextFromConnection}
                style={{ minWidth: 120 }}
              >
                Continue <ChevronRight size={14} />
              </button>
            </div>
          </div>
        </motion.div>
      )}

      {/* ── Step 2: Dossiers Selection ─────── */}
      {step === 1 && (
        <motion.div className="card card-pad" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, ease: [0.23,1,0.32,1] }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
            <Search size={15} style={{ color: 'var(--primary)' }} />
            <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>Dossier Estate Discovery</span>
          </div>
          <p style={{ fontSize: 13, color: 'var(--ink-3)', marginBottom: 20 }}>
            Source connection validated: <strong style={{ color: 'var(--ink)' }}>{form.mstr_base_url}</strong> (Project: {form.mstr_project_id})
          </p>

          <div style={{
            background: 'var(--field)',
            border: '1px dashed var(--line-strong)',
            borderRadius: 'var(--radius-md)',
            padding: '24px',
            textAlign: 'center',
            marginBottom: 20
          }}>
            <Database size={28} style={{ color: 'var(--ink-3)', margin: '0 auto 10px' }} />
            <p style={{ fontSize: 13, fontWeight: 500, color: 'var(--ink)', marginBottom: 4 }}>Full Estate Discovery Mode</p>
            <p style={{ fontSize: 12, color: 'var(--ink-3)', maxWidth: 460, margin: '0 auto' }}>
              The pipeline will automatically discover all Dossiers, Reports, Cubes, Attributes, Facts, and Metrics in the project using the 11-wave dependency graph.
            </p>
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', paddingTop: 8 }}>
            <button className="btn btn-ghost" onClick={() => setStep(0)}>Back</button>
            <button className="btn btn-primary" onClick={() => setStep(2)}>
              Proceed to Configure <ChevronRight size={14} />
            </button>
          </div>
        </motion.div>
      )}

      {/* ── Step 3: Configure & Launch ──────────────── */}
      {step === 2 && (
        <motion.div className="card card-pad" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, ease: [0.23,1,0.32,1] }}>
          <div style={{ display: 'grid', gap: 20, maxWidth: 540 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Sliders size={15} style={{ color: 'var(--primary)' }} />
              <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>Pipeline Execution Settings</span>
            </div>

            <div style={{ display: 'grid', gap: 14 }}>
              <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '12px 14px', borderRadius: 'var(--radius-sm)', background: 'var(--field)'
              }}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--ink)' }}>Auto-Publish to Production</div>
                  <div style={{ fontSize: 12, color: 'var(--ink-3)' }}>Only promotes when 4-gate scorecard exceeds threshold</div>
                </div>
                <input
                  type="checkbox"
                  checked={form.auto_publish}
                  onChange={e => setForm({ ...form, auto_publish: e.target.checked })}
                  style={{ accentColor: 'var(--primary)', width: 18, height: 18 }}
                  id="auto-publish"
                />
              </div>

              <div className="input-group">
                <label className="input-label" style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>Numeric Parity Gate Threshold (ADR-030)</span>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--primary)' }}>
                    {(form.numeric_threshold * 100).toFixed(0)}%
                  </span>
                </label>
                <input
                  type="range"
                  min="0.90"
                  max="1.0"
                  step="0.01"
                  value={form.numeric_threshold}
                  onChange={e => setForm({ ...form, numeric_threshold: parseFloat(e.target.value) })}
                  style={{ accentColor: 'var(--primary)', width: '100%' }}
                />
              </div>
            </div>

            <div style={{
              background: 'var(--primary-tint)',
              border: '1px solid var(--primary-tint-strong)',
              borderRadius: 'var(--radius-md)',
              padding: 16,
              display: 'flex', gap: 12
            }}>
              <ShieldCheck size={18} style={{ color: 'var(--primary)', flexShrink: 0, marginTop: 2 }} />
              <div>
                <p style={{ fontSize: 13, fontWeight: 600, color: 'var(--primary)' }}>Production Write-Lock Guaranteed (ADR-029)</p>
                <p style={{ fontSize: 12, color: 'var(--ink-2)', marginTop: 4 }}>
                  All artifacts will be emitted to <code style={{ fontFamily: 'var(--font-mono)' }}>_migration_staging</code> first. Production project <strong>{form.tableau_target_project}</strong> will only be updated if all 4 validation gates pass.
                </p>
              </div>
            </div>

            {apiError && (
              <div style={{
                padding: '10px 14px', borderRadius: 'var(--radius-sm)',
                background: 'var(--red-tint)', color: 'var(--red)', fontSize: 12
              }}>
                {apiError}
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'space-between', paddingTop: 8 }}>
              <button className="btn btn-ghost" onClick={() => setStep(1)}>Back</button>
              <button
                type="button"
                className="btn btn-primary"
                onClick={handleSubmit}
                disabled={loading || !isStep0Valid}
                style={{ minWidth: 140 }}
              >
                <Rocket size={14} />
                {loading ? 'Initiating Pipeline...' : 'Start Migration'}
              </button>
            </div>
          </div>
        </motion.div>
      )}
    </>
  );
}
