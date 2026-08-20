import React, { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  AlertTriangle,
  OctagonX,
  Info,
  CheckCircle2,
  ArrowLeft,
  Filter,
  Search,
  Check,
  RefreshCw,
  HelpCircle,
} from 'lucide-react';
import { api, type ReviewTask } from '../api';
import { IssueCard, type IssueItem } from '../components/migration/IssueCard';
import { EmptyState } from '../components/ui/EmptyState';

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
        setIssues(
          (res.tasks || []).map((t) => ({
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
            blast_radius: t.blast_radius || [],
          }))
        );
      })
      .catch(() => {
        setIssues([]);
      });
  }, [jobId]);

  const handleApprove = async (id: string) => {
    setResolvingId(id);
    try {
      await api.resolveReviewTask(id, { action: 'approve', notes: 'Approved via Issue Center UI' });
      setIssues((prev) =>
        prev.map((item) => (item.id === id ? { ...item, status: 'approved' } : item))
      );
    } catch (e) {
      // Local optimistic update
      setIssues((prev) =>
        prev.map((item) => (item.id === id ? { ...item, status: 'approved' } : item))
      );
    } finally {
      setResolvingId(null);
    }
  };

  const handleEdit = async (id: string, newCalc: string) => {
    try {
      await api.resolveReviewTask(id, { action: 'edit', edited_calc: newCalc });
      setIssues((prev) =>
        prev.map((item) =>
          item.id === id ? { ...item, generated_calc: newCalc, status: 'approved' } : item
        )
      );
    } catch (e) {
      setIssues((prev) =>
        prev.map((item) =>
          item.id === id ? { ...item, generated_calc: newCalc, status: 'approved' } : item
        )
      );
    }
  };



  const filteredIssues = issues.filter((i) => {
    const matchesSearch =
      i.object_name.toLowerCase().includes(search.toLowerCase()) ||
      i.reason.toLowerCase().includes(search.toLowerCase()) ||
      i.object_id.toLowerCase().includes(search.toLowerCase());

    const matchesSeverity = severityFilter === 'all' || i.severity === severityFilter;

    return matchesSearch && matchesSeverity;
  });

  const blockerCount = issues.filter((i) => i.severity === 'blocker' && i.status === 'pending').length;
  const warningCount = issues.filter((i) => i.severity === 'warning' && i.status === 'pending').length;
  const infoCount = issues.filter((i) => i.severity === 'info' && i.status === 'pending').length;

  return (
    <div style={{ maxWidth: '1440px', margin: '0 auto' }}>
      {/* ── Top Header ───────────────────────────────────────────── */}
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
            <h1
              style={{
                fontSize: '1.625rem',
                fontWeight: 700,
                color: 'var(--ink)',
                letterSpacing: '-0.02em',
                margin: 0,
              }}
            >
              Issue Center &amp; Ambiguity Review Queue
            </h1>
            <p style={{ fontSize: '0.875rem', color: 'var(--ink-2)', marginTop: '4px' }}>
              Actionable review items, LOD translation notes, and multi-option strategy approvals
            </p>
          </div>
        </div>
      </div>



      {/* ── Filter & Search Bar ──────────────────────────────────── */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '16px',
          marginBottom: '16px',
          flexWrap: 'wrap',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {[
            { key: 'all', label: `All Items (${issues.length})` },
            { key: 'blocker', label: `Blockers (${blockerCount})`, color: 'var(--red)' },
            { key: 'warning', label: `Warnings (${warningCount})`, color: 'var(--yellow)' },
            { key: 'info', label: `Info (${infoCount})`, color: 'var(--blue)' },
          ].map((f) => (
            <button
              key={f.key}
              onClick={() => setSeverityFilter(f.key as any)}
              style={{
                padding: '6px 14px',
                borderRadius: 'var(--radius-full)',
                border: '1px solid',
                borderColor: severityFilter === f.key ? 'var(--primary)' : 'var(--line)',
                background: severityFilter === f.key ? 'var(--primary-tint)' : 'var(--surface)',
                color: severityFilter === f.key ? 'var(--primary)' : f.color || 'var(--ink-2)',
                fontSize: '0.8125rem',
                fontWeight: severityFilter === f.key ? 600 : 500,
                cursor: 'pointer',
              }}
            >
              {f.label}
            </button>
          ))}
        </div>

        <div className="search-bar" style={{ minWidth: '320px' }}>
          <Search size={16} className="search-icon" />
          <input
            type="text"
            className="input"
            placeholder="Search issues by formula, object name, or blast radius..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      {/* ── Issues List ──────────────────────────────────────────── */}
      {filteredIssues.length === 0 ? (
        <EmptyState
          icon={CheckCircle2}
          title="All review items resolved"
          description="There are no pending ambiguity flags or validation blockers for this migration."
          actionLabel="Return to Control Center"
          onAction={() => { }}
        />
      ) : (
        <div>
          {filteredIssues.map((issue) => (
            <IssueCard
              key={issue.id}
              issue={issue}
              onApprove={handleApprove}
              onEdit={handleEdit}
              isResolving={resolvingId === issue.id}
            />
          ))}
        </div>
      )}
    </div>
  );
}
