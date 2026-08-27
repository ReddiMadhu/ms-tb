import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Rocket, Search, Database, Server, ChevronRight, CheckCircle2,
  ShieldCheck, AlertTriangle, RefreshCw, Layers, CheckSquare,
  Square, ArrowLeft, Globe, Lock, KeyRound, Sparkles, Check
} from 'lucide-react';
import { api, type DiscoveredDossier, type ConnectionValidation } from '../api';

const STEPS = [
  { label: 'Connection & Validation', icon: Server },
  { label: 'Dossier Estate Discovery', icon: Layers },
];

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

  // Connection validation state
  const [validationState, setValidationState] = useState<'idle' | 'validating' | 'connected' | 'failed'>('idle');
  const [validationResult, setValidationResult] = useState<ConnectionValidation | null>(null);
  const [devModeBypass, setDevModeBypass] = useState(false);

  // Dossier discovery state
  const [discovering, setDiscovering] = useState(false);
  const [discoveredDossiers, setDiscoveredDossiers] = useState<DiscoveredDossier[]>([]);
  const [discoveryError, setDiscoveryError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedDossierIds, setSelectedDossierIds] = useState<string[]>([]);
  const [scanDuration, setScanDuration] = useState<number | null>(null);

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

  const errors = {
    name: !form.name.trim() ? 'Job Name is required' : null,
    mstr_base_url: !form.mstr_base_url.trim()
      ? 'MSTR Server URL is required'
      : !form.mstr_base_url.startsWith('http://') && !form.mstr_base_url.startsWith('https://')
        ? 'URL must start with http:// or https://'
        : null,
    mstr_username: !form.mstr_username.trim() ? 'MSTR Username is required' : null,
    mstr_password: !form.mstr_password ? 'MSTR Password is required' : null,
    mstr_project_id: null,  // Not mandatory — user selects from discovered list
  };

  // Can test connection without project ID (to discover available projects)
  const canTestConnection = !errors.name && !errors.mstr_base_url && !errors.mstr_username && !errors.mstr_password;
  // Need project ID selected to proceed to next step
  const isStep0Valid = canTestConnection;

  const isConnectionVerified = validationState === 'connected' || devModeBypass;
  const hasTableauTarget = !!form.tableau_server_url.trim();

  const handleBlur = (field: string) => {
    setTouched(prev => ({ ...prev, [field]: true }));
  };

  // Reset validation state if connection parameters change
  const handleConnectionParamChange = (field: keyof FormState, value: string) => {
    setForm(prev => ({ ...prev, [field]: value }));
    // Only reset validation if server connection params change, NOT when selecting a project
    if (field !== 'mstr_project_id' && validationState !== 'idle') {
      setValidationState('idle');
      setValidationResult(null);
    }
  };

  // Trigger connection validation
  async function handleValidateConnection(autoAdvance = false): Promise<boolean> {
    setTouched({
      name: true,
      mstr_base_url: true,
      mstr_username: true,
      mstr_password: true,
      mstr_project_id: autoAdvance,  // Only mark project_id touched if advancing
    });

    if (autoAdvance && !isStep0Valid) return false;
    if (!canTestConnection) return false;

    setValidationState('validating');
    setApiError(null);

    try {
      const res = await api.validateConnection({
        mstr_base_url: form.mstr_base_url.trim(),
        mstr_username: form.mstr_username.trim(),
        mstr_password: form.mstr_password,
        mstr_project_id: form.mstr_project_id.trim(),
      });

      setValidationResult(res);

      if (res.valid) {
        setValidationState('connected');
        if (autoAdvance) {
          setTimeout(() => {
            setStep(1);
          }, 400);
        }
        return true;
      } else {
        setValidationState('failed');
        setApiError(res.error || 'Connection failed: could not authenticate with MicroStrategy server.');
        return false;
      }
    } catch (e: any) {
      setValidationState('failed');
      const msg = e?.message || 'Failed to connect to backend server or MSTR endpoint.';
      setApiError(msg);
      return false;
    }
  }

  // Trigger dossier discovery when entering step 1
  useEffect(() => {
    if (step === 1 && discoveredDossiers.length === 0 && !discovering && !discoveryError) {
      loadDossiers();
    }
  }, [step]);

  async function loadDossiers() {
    setDiscovering(true);
    setDiscoveryError(null);
    try {
      const res = await api.discoverDossiers({
        mstr_base_url: form.mstr_base_url.trim(),
        mstr_username: form.mstr_username.trim(),
        mstr_password: form.mstr_password,
        mstr_project_id: form.mstr_project_id.trim(),
      });
      setDiscoveredDossiers(res.dossiers || []);
      setScanDuration(res.scan_duration_ms);
      // Default: select all discovered dossiers
      setSelectedDossierIds((res.dossiers || []).map(d => d.mstr_id));
    } catch (e: any) {
      console.warn('Dossier discovery failed or offline:', e);
      setDiscoveryError(e?.message || 'Could not fetch dossiers from server.');
      // If mock/empty, allow continuing in full-estate mode
    } finally {
      setDiscovering(false);
    }
  }

  const toggleSelectDossier = (id: string) => {
    setSelectedDossierIds(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
    );
  };

  const toggleSelectAll = () => {
    if (selectedDossierIds.length === filteredDossiers.length) {
      setSelectedDossierIds([]);
    } else {
      setSelectedDossierIds(filteredDossiers.map(d => d.mstr_id));
    }
  };

  const filteredDossiers = discoveredDossiers.filter(d =>
    d.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    (d.path && d.path.toLowerCase().includes(searchQuery.toLowerCase())) ||
    (d.owner && d.owner.toLowerCase().includes(searchQuery.toLowerCase()))
  );

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
        tableau_server_url: form.tableau_server_url || undefined,
        tableau_site_id: form.tableau_site_id,
        tableau_target_project: form.tableau_target_project,
        selected_dossier_ids: selectedDossierIds.length > 0 ? selectedDossierIds : undefined,
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
      <div className="page-header-gradient">
        <div className="page-header">
          <h1 className="page-title">New Migration Job</h1>
          <p className="page-subtitle">Validate source connectivity, discover dossiers, and launch migration</p>
        </div>

        {/* ── Wizard Stepper ──────────────────────────────── */}
        <div className="wizard-stepper">
          {STEPS.map((s, i) => {
            const isCompleted = i < step;
            const isActive = i === step;
            const canJump = i === 0 || (i === 1 && isConnectionVerified);

            return (
              <button
                key={s.label}
                type="button"
                className={`wizard-step ${isActive ? 'active' : ''} ${isCompleted ? 'completed' : ''}`}
                disabled={!canJump}
                onClick={() => {
                  if (canJump) setStep(i);
                }}
              >
                <div className="wizard-step-number">
                  {isCompleted ? <Check size={12} strokeWidth={3} /> : (i + 1)}
                </div>
                <span>{s.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* ── Step 1: Connection & Credentials ────────────────── */}
      {step === 0 && (
        <motion.div
          className="card card-pad"
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, ease: [0.23, 1, 0.32, 1] }}
        >
          <div className="new-job-grid">
            {/* ═══ LEFT COLUMN: Source Connection & Identification ═══ */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
              {/* Job Identification */}
              <div>
                <div className="section-header" style={{ marginBottom: 10 }}>
                  <div className="section-title">Job Identification</div>
                </div>

                <div className="input-group">
                  <label className="input-label" style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span>Job Name <span style={{ color: 'var(--primary)' }}>*</span></span>
                    {touched.name && errors.name && (
                      <span style={{ color: 'var(--red)', fontSize: 11 }}>{errors.name}</span>
                    )}
                  </label>
                  <input
                    className={`input ${touched.name && errors.name ? 'input-error' : ''}`}
                    placeholder="e.g. Q3 2026 Sales Analytics Migration"
                    value={form.name}
                    onBlur={() => handleBlur('name')}
                    onChange={e => setForm({ ...form, name: e.target.value })}
                  />
                </div>
              </div>

              {/* MSTR Source Section */}
              <div style={{ borderTop: '1px solid var(--line)', paddingTop: 16 }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
                  <div className="section-header" style={{ marginBottom: 0 }}>
                    <div className="section-title">MicroStrategy Source Connection</div>
                  </div>

                  {/* Connection Status Pill */}
                  <div className={`connection-status ${validationState}`}>
                    <span className={`connection-dot ${validationState === 'validating' ? 'pulse' : ''}`} />
                    <span>
                      {validationState === 'validating' && 'Verifying...'}
                      {validationState === 'connected' && 'Connected & Verified'}
                      {validationState === 'failed' && 'Verification Failed'}
                      {validationState === 'idle' && 'Unverified'}
                    </span>
                  </div>
                </div>

                <div style={{ display: 'grid', gap: 12 }}>
                  <div className="input-group">
                    <label className="input-label" style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span>Library REST API URL <span style={{ color: 'var(--primary)' }}>*</span></span>
                      {touched.mstr_base_url && errors.mstr_base_url && (
                        <span style={{ color: 'var(--red)', fontSize: 11 }}>{errors.mstr_base_url}</span>
                      )}
                    </label>
                    <input
                      className={`input ${touched.mstr_base_url && errors.mstr_base_url ? 'input-error' : ''}`}
                      placeholder="https://mstr.company.com/MicroStrategyLibrary"
                      value={form.mstr_base_url}
                      onBlur={() => handleBlur('mstr_base_url')}
                      onChange={e => handleConnectionParamChange('mstr_base_url', e.target.value)}
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
                        className={`input ${touched.mstr_username && errors.mstr_username ? 'input-error' : ''}`}
                        placeholder="e.g. administrator"
                        value={form.mstr_username}
                        onBlur={() => handleBlur('mstr_username')}
                        onChange={e => handleConnectionParamChange('mstr_username', e.target.value)}
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
                        className={`input ${touched.mstr_password && errors.mstr_password ? 'input-error' : ''}`}
                        type="password"
                        placeholder="••••••••••••"
                        value={form.mstr_password}
                        onBlur={() => handleBlur('mstr_password')}
                        onChange={e => handleConnectionParamChange('mstr_password', e.target.value)}
                      />
                    </div>
                  </div>

                  <div className="input-group">
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                      <label className="input-label" style={{ marginBottom: 0 }}>
                        <span>MSTR Project ID (GUID)</span>
                        {touched.mstr_project_id && errors.mstr_project_id && (
                          <span style={{ color: 'var(--red)', fontSize: 11, marginLeft: 8 }}>{errors.mstr_project_id}</span>
                        )}
                      </label>

                      <button
                        type="button"
                        className="btn btn-secondary btn-xs"
                        disabled={validationState === 'validating' || !canTestConnection}
                        onClick={() => handleValidateConnection(false)}
                        style={{ padding: '2px 8px', fontSize: 11, display: 'inline-flex', alignItems: 'center', gap: 4 }}
                        title={!canTestConnection ? 'Enter URL, Username & Password to fetch projects' : 'Fetch available projects from server'}
                      >
                        <RefreshCw size={11} className={validationState === 'validating' ? 'spinner' : ''} />
                        {validationState === 'validating' ? 'Fetching...' : 'Fetch Projects'}
                      </button>
                    </div>

                    <input
                      className={`input ${touched.mstr_project_id && errors.mstr_project_id ? 'input-error' : ''}`}
                      style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}
                      placeholder="B7CA92F04B9FAE8D941C3E9B7E0CD754"
                      value={form.mstr_project_id}
                      onBlur={() => handleBlur('mstr_project_id')}
                      onChange={e => handleConnectionParamChange('mstr_project_id', e.target.value)}
                    />

                    {validationResult?.projects && validationResult.projects.length > 0 && (
                      <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
                        <span style={{ fontSize: 11, color: 'var(--ink-2)' }}>
                          Available Projects on Server ({validationResult.projects.length}):
                        </span>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                          {validationResult.projects.map(p => (
                            <button
                              key={p.id}
                              type="button"
                              className={`badge ${form.mstr_project_id === p.id ? 'badge-primary' : 'badge-neutral'}`}
                              style={{ cursor: 'pointer', border: '1px solid var(--line)', padding: '4px 8px' }}
                              onClick={() => handleConnectionParamChange('mstr_project_id', p.id)}
                              title={`ID: ${p.id}${p.description ? ' - ' + p.description : ''}`}
                            >
                              {p.name} {p.id === form.mstr_project_id && '✓'}
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>

            {/* ═══ RIGHT COLUMN: Tableau Target & Live Validation Feedback ═══ */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
              {/* Tableau Target Section — OPTIONAL */}
              <div>
                <div className="section-header" style={{ marginBottom: 10 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span className="section-title">Tableau Target Destination</span>
                    <span className={`badge ${hasTableauTarget ? 'badge-success' : 'badge-neutral'}`}>
                      {hasTableauTarget ? 'Connected' : 'Optional (Download-Only)'}
                    </span>
                  </div>
                </div>

                <div style={{ display: 'grid', gap: 12 }}>
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
            </div>
          </div>

          {/* Action Bar */}
          <div style={{ marginTop: 20, paddingTop: 16, borderTop: '1px solid var(--line)' }}>
            <AnimatePresence>

              {validationState === 'failed' && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  style={{ marginBottom: 14 }}
                >
                  <div className="inline-banner error">
                    <AlertTriangle size={18} className="inline-banner-icon" />
                    <div style={{ flex: 1 }}>
                      <strong>Connection Validation Failed</strong>
                      <div style={{ fontSize: 12, marginTop: 2, opacity: 0.9 }}>
                        {apiError || 'Could not connect to MSTR Library REST API. Please check server URL, username, and password.'}
                      </div>
                      <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 8 }}>
                        <label style={{ fontSize: 11, display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                          <input
                            type="checkbox"
                            checked={devModeBypass}
                            onChange={e => setDevModeBypass(e.target.checked)}
                            style={{ accentColor: 'var(--primary)' }}
                          />
                          <span>Bypass validation for Offline / Dev Mode Testing</span>
                        </label>
                      </div>
                    </div>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <button
                type="button"
                className="btn btn-secondary"
                disabled={validationState === 'validating' || !canTestConnection}
                onClick={() => handleValidateConnection(false)}
              >
                {validationState === 'validating' ? (
                  <span className="spinner sm" />
                ) : (
                  <RefreshCw size={14} />
                )}
                Test Connection
              </button>

              <button
                type="button"
                className="btn btn-primary"
                disabled={validationState === 'validating' || (!isConnectionVerified && !isStep0Valid)}
                onClick={async () => {
                  if (!form.mstr_project_id.trim() && validationResult?.projects?.length) {
                    setTouched(prev => ({ ...prev, mstr_project_id: true }));
                    return;
                  }
                  if (isConnectionVerified && isStep0Valid) {
                    setStep(1);
                  } else {
                    await handleValidateConnection(true);
                  }
                }}
                style={{ minWidth: 160 }}
              >
                {validationState === 'validating' ? (
                  <>
                    <span className="spinner sm white" />
                    Validating...
                  </>
                ) : (
                  <>
                    Validate & Continue <ChevronRight size={14} />
                  </>
                )}
              </button>
            </div>
          </div>
        </motion.div>
      )}

      {/* ── Step 2: Dossier Estate Discovery ─────── */}
      {step === 1 && (
        <motion.div
          className="card card-pad"
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, ease: [0.23, 1, 0.32, 1] }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
            <div className="section-header" style={{ marginBottom: 0 }}>
              <div className="section-title">Dossier Estate Discovery</div>
            </div>

            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={loadDossiers}
              disabled={discovering}
            >
              <RefreshCw size={12} className={discovering ? 'spinner' : ''} />
              Rescan Estate
            </button>
          </div>

          <div style={{
            background: 'var(--field)',
            borderRadius: 'var(--radius-md)',
            padding: '12px 16px',
            marginBottom: 20,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            fontSize: 12
          }}>
            <div>
              Source: <strong style={{ color: 'var(--ink)' }}>{form.mstr_base_url}</strong>
              <span style={{ color: 'var(--ink-3)', margin: '0 8px' }}>•</span>
              Project: <code style={{ fontFamily: 'var(--font-mono)' }}>{form.mstr_project_id}</code>
            </div>
            {scanDuration !== null && (
              <span style={{ color: 'var(--ink-3)', fontFamily: 'var(--font-mono)' }}>
                Scanned in {scanDuration}ms
              </span>
            )}
          </div>

          {/* Discovery Loading */}
          {discovering && (
            <div style={{ padding: '32px 20px', textAlign: 'center' }}>
              <div className="spinner lg" style={{ margin: '0 auto 16px' }} />
              <p style={{ fontSize: 14, fontWeight: 500, color: 'var(--ink)' }}>Scanning MicroStrategy Estate...</p>
              <p style={{ fontSize: 12, color: 'var(--ink-3)', marginTop: 4 }}>
                Discovering dossiers, reports, datasets, and attribute hierarchies
              </p>
            </div>
          )}

          {/* Discovery Error / Offline Fallback */}
          {!discovering && discoveryError && (
            <div style={{ marginBottom: 20 }}>
              <div className="inline-banner warning">
                <AlertTriangle size={18} className="inline-banner-icon" />
                <div style={{ flex: 1 }}>
                  <strong>Estate Scan Incomplete</strong>
                  <p style={{ fontSize: 12, marginTop: 2 }}>{discoveryError}</p>
                  <p style={{ fontSize: 12, marginTop: 4, opacity: 0.9 }}>
                    You can still proceed in <strong>Full Estate Discovery Mode</strong>. The pipeline will discover all objects during the execution phase.
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Discovered Dossiers Table / Selector */}
          {!discovering && discoveredDossiers.length > 0 && (
            <>
              <div style={{ display: 'flex', gap: 12, marginBottom: 14, alignItems: 'center' }}>
                <div className="search-bar" style={{ flex: 1 }}>
                  <Search size={14} className="search-icon" />
                  <input
                    className="input"
                    placeholder="Filter discovered dossiers by name, path, owner..."
                    value={searchQuery}
                    onChange={e => setSearchQuery(e.target.value)}
                  />
                </div>

                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={toggleSelectAll}
                >
                  {selectedDossierIds.length === filteredDossiers.length ? (
                    <>
                      <CheckSquare size={13} /> Deselect All
                    </>
                  ) : (
                    <>
                      <Square size={13} /> Select All ({filteredDossiers.length})
                    </>
                  )}
                </button>
              </div>

              <div style={{
                border: '1px solid var(--line)',
                borderRadius: 'var(--radius-md)',
                maxHeight: 320,
                overflowY: 'auto',
                marginBottom: 20
              }}>
                <div className="dossier-list">
                  {filteredDossiers.map(dossier => {
                    const isSelected = selectedDossierIds.includes(dossier.mstr_id);
                    return (
                      <div
                        key={dossier.mstr_id}
                        className={`dossier-item ${isSelected ? 'selected' : ''}`}
                        onClick={() => toggleSelectDossier(dossier.mstr_id)}
                      >
                        <input
                          type="checkbox"
                          className="dossier-checkbox"
                          checked={isSelected}
                          onChange={() => { }} // Handled by container
                        />
                        <div className="dossier-info">
                          <div className="dossier-name">{dossier.name}</div>
                          <div className="dossier-meta">
                            {dossier.path && <span>Path: {dossier.path}</span>}
                            {dossier.owner && <span>Owner: {dossier.owner}</span>}
                            <span>ID: <code style={{ fontFamily: 'var(--font-mono)' }}>{dossier.mstr_id.slice(0, 8)}...</code></span>
                          </div>
                        </div>
                        <div style={{ display: 'flex', gap: 6 }}>
                          {dossier.metric_count > 0 && (
                            <span className="badge badge-neutral" style={{ fontSize: 10 }}>
                              {dossier.metric_count} Metrics
                            </span>
                          )}
                          {dossier.attribute_count > 0 && (
                            <span className="badge badge-neutral" style={{ fontSize: 10 }}>
                              {dossier.attribute_count} Attributes
                            </span>
                          )}
                        </div>
                      </div>
                    );
                  })}
                  {filteredDossiers.length === 0 && (
                    <div style={{ padding: 24, textAlign: 'center', color: 'var(--ink-3)', fontSize: 13 }}>
                      No dossiers match your search filter "{searchQuery}"
                    </div>
                  )}
                </div>
              </div>

              <div style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginBottom: 20,
                fontSize: 12,
                color: 'var(--ink-2)'
              }}>
                <span>
                  <strong>{selectedDossierIds.length}</strong> of {discoveredDossiers.length} dossiers selected for migration
                </span>
                {selectedDossierIds.length === 0 && (
                  <span style={{ color: 'var(--yellow)' }}>
                    (No dossiers selected — will run in full estate discovery mode)
                  </span>
                )}
              </div>
            </>
          )}

          {/* Full Estate Discovery Banner when empty */}
          {!discovering && discoveredDossiers.length === 0 && (
            <div style={{
              background: 'var(--field)',
              border: '1px dashed var(--line-strong)',
              borderRadius: 'var(--radius-md)',
              padding: '28px',
              textAlign: 'center',
              marginBottom: 20
            }}>
              <Database size={32} style={{ color: 'var(--primary)', margin: '0 auto 12px' }} />
              <p style={{ fontSize: 14, fontWeight: 600, color: 'var(--ink)', marginBottom: 4 }}>Full Estate Discovery Mode</p>
              <p style={{ fontSize: 12, color: 'var(--ink-3)', maxWidth: 480, margin: '0 auto' }}>
                The pipeline will automatically discover all Dossiers, Reports, Cubes, Attributes, Facts, and Metrics in the project using the 11-wave dependency graph.
              </p>
            </div>
          )}

          {apiError && (
            <div className="inline-banner error" style={{ marginBottom: 16 }}>
              <AlertTriangle size={16} className="inline-banner-icon" />
              <span style={{ fontSize: 12 }}>{apiError}</span>
            </div>
          )}

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingTop: 8 }}>
            <button className="btn btn-ghost" onClick={() => setStep(0)}>
              <ArrowLeft size={14} /> Back to Connection
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleSubmit}
              disabled={loading || !isStep0Valid}
              style={{ minWidth: 160 }}
            >
              {loading ? (
                <>
                  <span className="spinner sm white" />
                  Initiating Pipeline...
                </>
              ) : (
                <>
                  <Rocket size={14} />
                  Start Migration
                </>
              )}
            </button>
          </div>
        </motion.div>
      )}
    </>
  );
}
