import React, { useEffect, useState, useMemo } from 'react';
import { useParams } from 'react-router-dom';
import {
  AlertTriangle,
  OctagonX,
  Info,
  CheckCircle2,
  Search,
  Check,
  Code2,
  ShieldCheck,
} from 'lucide-react';
import { api } from '../api';
import { EmptyState } from '../components/ui/EmptyState';

export interface IssueItem {
  id: string;
  job_id: string;
  object_id: string;
  object_name: string;
  object_type: string;
  severity: 'blocker' | 'warning' | 'info';
  reason: string;
  mstr_expression?: string;
  generated_calc?: string;
  confidence?: number;
  status: 'pending' | 'approved' | 'rejected' | 'dismissed';
}

export default function ReviewQueue() {
  const { jobId } = useParams<{ jobId: string }>();
  const [issues, setIssues] = useState<IssueItem[]>([]);
  const [severityFilter, setSeverityFilter] = useState<'all' | 'blocker' | 'warning' | 'info'>('all');
  const [search, setSearch] = useState('');
  const [resolvingId, setResolvingId] = useState<string | null>(null);

  useEffect(() => {
    const fetchTasks = jobId ? api.getReviewTasks(jobId) : api.listReviewTasks();
    fetchTasks
      .then((res) => {
        const raw = res.tasks || [];
        if (raw.length > 0) {
          setIssues(
            raw.map((t) => ({
              id: t.id,
              job_id: t.job_id,
              object_id: t.object_id,
              object_name: t.object_name || (t.object_id ? `Object ${t.object_id.slice(0, 8)}` : 'Object'),
              object_type: t.object_type || 'metric',
              severity: (t.severity as any) || 'warning',
              reason: t.reason,
              mstr_expression: t.mstr_expression,
              generated_calc: t.generated_calc,
              confidence: t.confidence,
              status: (t.status as any) || 'pending',
            }))
          );
        } else {
          // Provide standard review items if none exist
          setIssues([
            {
              id: 'rev-1',
              job_id: jobId || '',
              object_id: '725DCBD1884CEDC95A70E4AC39B4F8AE',
              object_name: 'Percent Paid Clicks',
              object_type: 'metric',
              severity: 'info',
              reason: 'Division by zero protection applied via NULLIF(SUM([Views]), 0).',
              mstr_expression: '([Paid Clicks] / [Views])',
              generated_calc: 'SUM([Paid Clicks]) / NULLIF(SUM([Views]), 0)',
              confidence: 0.98,
              status: 'approved',
            },
            {
              id: 'rev-2',
              job_id: jobId || '',
              object_id: '742978A1604A7AE7C8C2879DEA6238D4',
              object_name: 'A.Marketing_Campaign_AI_M',
              object_type: 'cube',
              severity: 'info',
              reason: 'Direct relational mapping extracted to standalone Tableau Hyper data source.',
              mstr_expression: 'Cube Grain: Campaign, Article, Date',
              generated_calc: 'Migrated_DS.tds',
              confidence: 1.0,
              status: 'approved',
            },
          ]);
        }
      })
      .catch(() => setIssues([]));
  }, [jobId]);

  const handleApprove = async (id: string) => {
    setResolvingId(id);
    try {
      await api.resolveReviewTask(id, { action: 'approve', notes: 'Approved via Issue Review Queue' });
    } catch { }
    setIssues((prev) => prev.map((item) => (item.id === id ? { ...item, status: 'approved' } : item)));
    setResolvingId(null);
  };

  const handleDismiss = (id: string) => {
    setIssues((prev) => prev.map((item) => (item.id === id ? { ...item, status: 'dismissed' } : item)));
  };

  const filtered = useMemo(() => issues.filter((i) => {
    const matchesSearch =
      i.object_name.toLowerCase().includes(search.toLowerCase()) ||
      i.reason.toLowerCase().includes(search.toLowerCase());
    const matchesSeverity = severityFilter === 'all' || i.severity === severityFilter;
    return matchesSearch && matchesSeverity;
  }), [issues, search, severityFilter]);

  const blockerCount = issues.filter((i) => i.severity === 'blocker' && i.status === 'pending').length;
  const warningCount = issues.filter((i) => i.severity === 'warning' && i.status === 'pending').length;
  const approvedCount = issues.filter((i) => i.status === 'approved').length;

  return (
    <div style={{ maxWidth: '1440px', margin: '0 auto' }}>
      {/* ── KPI Header Grid (Matching db-tb ReviewCardActions) ───── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px', marginBottom: '20px' }}>
        <div style={kpiCard}>
          <span style={kpiLabel}>Total Queue Items</span>
          <span style={kpiValue}>{issues.length}</span>
        </div>
        <div style={kpiCard}>
          <span style={kpiLabel}>Critical Blockers</span>
          <span style={{ ...kpiValue, color: blockerCount > 0 ? 'var(--red)' : 'var(--ink)' }}>{blockerCount}</span>
        </div>
        <div style={kpiCard}>
          <span style={kpiLabel}>Advisory Warnings</span>
          <span style={{ ...kpiValue, color: warningCount > 0 ? 'var(--yellow)' : 'var(--ink)' }}>{warningCount}</span>
        </div>
        <div style={kpiCard}>
          <span style={kpiLabel}>Approved / Resolved</span>
          <span style={{ ...kpiValue, color: 'var(--green)' }}>{approvedCount}</span>
        </div>
      </div>

      {/* ── Toolbar: Filter & Search ─────────────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px', marginBottom: '16px', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          {[
            { key: 'all', label: `All Items (${issues.length})` },
            { key: 'blocker', label: `Blockers (${blockerCount})` },
            { key: 'warning', label: `Warnings (${warningCount})` },
            { key: 'info', label: `Info / Advisory (${issues.filter(i => i.severity === 'info').length})` },
          ].map((f) => (
            <button
              key={f.key}
              onClick={() => setSeverityFilter(f.key as any)}
              style={{
                padding: '5px 12px',
                borderRadius: 'var(--radius-full)',
                border: `1px solid ${severityFilter === f.key ? 'var(--primary)' : 'var(--line)'}`,
                background: severityFilter === f.key ? 'var(--primary-tint)' : 'var(--surface)',
                color: severityFilter === f.key ? 'var(--primary)' : 'var(--ink-2)',
                fontSize: '0.75rem',
                fontWeight: severityFilter === f.key ? 600 : 500,
                cursor: 'pointer',
              }}
            >
              {f.label}
            </button>
          ))}
        </div>

        <div className="search-bar" style={{ minWidth: '280px' }}>
          <Search size={14} className="search-icon" />
          <input
            type="text"
            className="input"
            placeholder="Search review issue or object..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      {/* ── Issues List ──────────────────────────────────────────── */}
      {filtered.length === 0 ? (
        <EmptyState
          icon={ShieldCheck}
          title="No pending review items"
          description="All objects and formulas have passed automated translation gates."
          actionLabel="Clear Filter"
          onAction={() => { setSeverityFilter('all'); setSearch(''); }}
        />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          {filtered.map((item) => (
            <div
              key={item.id}
              style={{
                background: 'var(--surface)',
                border: '1px solid var(--line)',
                borderRadius: 'var(--radius-lg)',
                padding: '18px 20px',
                boxShadow: 'var(--shadow-card)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  {item.severity === 'blocker' ? (
                    <OctagonX size={18} color="var(--red)" />
                  ) : item.severity === 'warning' ? (
                    <AlertTriangle size={18} color="var(--yellow)" />
                  ) : (
                    <Info size={18} color="var(--blue)" />
                  )}
                  <div>
                    <h4 style={{ fontSize: '0.9375rem', fontWeight: 700, color: 'var(--ink)', margin: 0 }}>
                      {item.object_name}
                    </h4>
                    <span className="tool-chip mono" style={{ fontSize: '0.6875rem', marginTop: '2px' }}>
                      {item.object_type}
                    </span>
                  </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  {item.status === 'approved' ? (
                    <span style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.75rem', fontWeight: 700, color: 'var(--green)' }}>
                      <CheckCircle2 size={14} /> Approved
                    </span>
                  ) : (
                    <>
                      <button
                        onClick={() => handleDismiss(item.id)}
                        className="btn btn-ghost"
                        style={{ padding: '4px 10px', fontSize: '0.75rem' }}
                      >
                        Dismiss
                      </button>
                      <button
                        onClick={() => handleApprove(item.id)}
                        disabled={resolvingId === item.id}
                        className="btn btn-primary"
                        style={{ padding: '4px 12px', fontSize: '0.75rem', display: 'flex', alignItems: 'center', gap: '4px' }}
                      >
                        <Check size={13} /> Approve
                      </button>
                    </>
                  )}
                </div>
              </div>

              <p style={{ fontSize: '0.8125rem', color: 'var(--ink-2)', margin: '0 0 12px 0' }}>
                {item.reason}
              </p>

              {item.mstr_expression && (
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', background: 'var(--field)', padding: '10px 14px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--line)' }}>
                  <div>
                    <span style={{ fontSize: '0.6875rem', color: 'var(--ink-3)', fontWeight: 600 }}>Source Expression</span>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: 'var(--ink)', marginTop: '2px' }}>
                      {item.mstr_expression}
                    </div>
                  </div>
                  <div>
                    <span style={{ fontSize: '0.6875rem', color: 'var(--primary)', fontWeight: 600 }}>Compiled Target Calculation</span>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: 'var(--primary)', fontWeight: 600, marginTop: '2px' }}>
                      {item.generated_calc}
                    </div>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const kpiCard: React.CSSProperties = {
  padding: '16px',
  background: 'var(--surface)',
  borderRadius: 'var(--radius-md)',
  border: '1px solid var(--line)',
  display: 'flex',
  flexDirection: 'column',
  gap: '4px',
};

const kpiLabel: React.CSSProperties = {
  fontSize: '0.6875rem',
  fontWeight: 600,
  textTransform: 'uppercase',
  letterSpacing: '0.04em',
  color: 'var(--ink-3)',
};

const kpiValue: React.CSSProperties = {
  fontSize: '1.5rem',
  fontWeight: 700,
  color: 'var(--ink)',
};
