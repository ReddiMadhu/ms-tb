import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api, type Job } from '../api';
import {
  FolderKanban,
  CheckCircle2,
  AlertTriangle,
  Clock,
  ArrowRight,
  Plus,
  Radio,
  ExternalLink,
  Layers,
  ArrowRightLeft,
  ShieldCheck,
  RefreshCw,
  Search,
} from 'lucide-react';
import { StatusBadge } from '../components/ui/StatusBadge';
import { KpiCard } from '../components/ui/KpiCard';
import { EmptyState } from '../components/ui/EmptyState';

export default function Dashboard() {
  const navigate = useNavigate();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');

  const fetchJobs = React.useCallback(async () => {
    try {
      const res = await api.listJobs();
      setJobs(res.jobs || []);
      setError(null);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to connect to migration backend API';
      setError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  const activeJobs = jobs.filter((j) => ['RUNNING', 'PENDING', 'PROMOTING'].includes(j.status)).length;

  useEffect(() => {
    fetchJobs();
  }, [fetchJobs]);

  useEffect(() => {
    // Only poll when active jobs are in-flight (10s interval as per spec)
    if (activeJobs === 0) return;

    const interval = setInterval(() => {
      fetchJobs();
    }, 10000);

    return () => clearInterval(interval);
  }, [activeJobs, fetchJobs]);

  // Compute KPI metrics
  const totalJobs = jobs.length;
  const completedJobs = jobs.filter((j) => ['COMPLETE', 'COMPLETE_WITH_WARNINGS', 'PUBLISHED'].includes(j.status)).length;
  const reviewRequired = jobs.filter((j) => j.status === 'NEEDS_REVIEW' || (j.review_queue_count && j.review_queue_count > 0)).length;

  const filteredJobs = jobs.filter((j) => {
    const matchesSearch =
      j.name.toLowerCase().includes(search.toLowerCase()) ||
      j.id.toLowerCase().includes(search.toLowerCase()) ||
      (j.mstr_project_id && j.mstr_project_id.toLowerCase().includes(search.toLowerCase()));

    const matchesStatus =
      statusFilter === 'all' ||
      (statusFilter === 'active' && ['RUNNING', 'PENDING', 'PROMOTING'].includes(j.status)) ||
      (statusFilter === 'completed' && ['COMPLETE', 'COMPLETE_WITH_WARNINGS', 'PUBLISHED'].includes(j.status)) ||
      (statusFilter === 'review' && (j.status === 'NEEDS_REVIEW' || (j.review_queue_count && j.review_queue_count > 0))) ||
      j.status.toLowerCase() === statusFilter.toLowerCase();

    return matchesSearch && matchesStatus;
  });

  return (
    <div style={{ maxWidth: '1440px', margin: '0 auto' }}>
      {/* ── Page Header ─────────────────────────────────────────── */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: '24px',
        }}
      >
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
            Migration Workspace
          </h1>
          <p
            style={{
              fontSize: '0.875rem',
              color: 'var(--ink-2)',
              marginTop: '4px',
            }}
          >
            Enterprise MicroStrategy to Tableau migration control center and observability hub
          </p>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <button
            type="button"
            onClick={fetchJobs}
            className="btn btn-secondary"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              padding: '8px 14px',
              fontSize: '0.8125rem',
            }}
            title="Refresh jobs"
          >
            <RefreshCw size={14} className={loading ? 'spin-icon' : ''} />
            <span>Refresh</span>
          </button>

          <Link
            to="/jobs/new"
            className="btn btn-primary"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              padding: '8px 16px',
              fontSize: '0.8125rem',
              fontWeight: 600,
            }}
          >
            <Plus size={16} />
            <span>New Migration</span>
          </Link>
        </div>
      </div>

      {/* ── KPI Row ─────────────────────────────────────────────── */}
      <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))' }}>
        <KpiCard
          title="Total Migration Jobs"
          value={totalJobs}
          subtitle="Registered migration workflows"
          icon={<FolderKanban size={20} />}
          accentColor="var(--primary)"
        />
        <KpiCard
          title="Completed & Verified"
          value={completedJobs}
          subtitle="Ready for production publish"
          icon={<CheckCircle2 size={20} />}
          accentColor="var(--green)"
        />
      </div>

      {/* ── Filter & Search Bar ─────────────────────────────────── */}
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
          {['all', 'active', 'completed'].map((f) => (
            <button
              key={f}
              onClick={() => setStatusFilter(f)}
              style={{
                padding: '6px 14px',
                borderRadius: 'var(--radius-full)',
                border: '1px solid',
                borderColor: statusFilter === f ? 'var(--primary)' : 'var(--line)',
                background: statusFilter === f ? 'var(--primary-tint)' : 'var(--surface)',
                color: statusFilter === f ? 'var(--primary)' : 'var(--ink-2)',
                fontSize: '0.8125rem',
                fontWeight: statusFilter === f ? 600 : 500,
                cursor: 'pointer',
                textTransform: 'capitalize',
                transition: 'all 0.15s ease',
              }}
            >
              {f === 'all'
                ? 'All Migrations'
                : `${f} Jobs`}
            </button>
          ))}
        </div>

        <div className="search-bar" style={{ minWidth: '280px' }}>
          <Search size={16} className="search-icon" />
          <input
            type="text"
            className="input"
            placeholder="Search by job name, ID, or project..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      {/* ── Error Banner (When cached jobs exist) ──────────────── */}
      {error && jobs.length > 0 && (
        <div
          style={{
            padding: '12px 16px',
            marginBottom: '16px',
            background: 'var(--red-tint, rgba(239, 68, 68, 0.1))',
            border: '1px solid var(--red, #ef4444)',
            borderRadius: 'var(--radius-md)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '12px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <AlertTriangle size={16} color="var(--red, #ef4444)" />
            <span style={{ fontSize: '0.8125rem', color: 'var(--ink)' }}>
              <strong>Sync Warning:</strong> {error}
            </span>
          </div>
          <button
            type="button"
            onClick={() => {
              setLoading(true);
              fetchJobs();
            }}
            className="btn btn-secondary"
            style={{
              padding: '4px 10px',
              fontSize: '0.75rem',
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
            }}
          >
            <RefreshCw size={12} />
            <span>Retry</span>
          </button>
        </div>
      )}

      {/* ── Jobs Table / Empty State ────────────────────────────── */}
      {loading && jobs.length === 0 ? (
        <div
          style={{
            padding: '60px',
            textAlign: 'center',
            background: 'var(--surface)',
            borderRadius: 'var(--radius-lg)',
            border: '1px solid var(--line)',
          }}
        >
          <RefreshCw size={28} className="spin-icon" color="var(--primary)" />
          <p style={{ marginTop: '14px', color: 'var(--ink-2)', fontSize: '0.875rem' }}>
            Loading migration catalog...
          </p>
        </div>
      ) : error && jobs.length === 0 ? (
        <EmptyState
          icon={AlertTriangle}
          title="Backend Connection Failed"
          description={`Unable to reach the backend migration service: ${error}. Verify that the backend server is running and reachable.`}
          actionLabel="Retry Connection"
          onAction={() => {
            setLoading(true);
            fetchJobs();
          }}
          actionIcon={<RefreshCw size={16} />}
        />
      ) : filteredJobs.length === 0 ? (
        <EmptyState
          icon={FolderKanban}
          title={search ? 'No matching migrations found' : 'No migration jobs yet'}
          description={
            search
              ? `No jobs match your search query "${search}". Try clearing your filters.`
              : 'Connect your MicroStrategy environment and discover dossiers to start your first automated migration.'
          }
          actionLabel={search ? 'Clear Filters' : 'Launch New Migration'}
          onAction={search ? () => { setSearch(''); setStatusFilter('all'); } : () => navigate('/jobs/new')}
          actionIcon={<Plus size={16} />}
        />
      ) : (
        <div
          style={{
            background: 'var(--surface)',
            border: '1px solid var(--line)',
            borderRadius: 'var(--radius-lg)',
            overflow: 'hidden',
            boxShadow: 'var(--shadow-card)',
          }}
        >
          <table className="log-table">
            <thead>
              <tr>
                <th>Migration Job</th>
                <th>Status</th>
                <th>Current Stage</th>
                <th>Objects Progress</th>
                <th>Confidence</th>
                <th>Created</th>
                <th style={{ textAlign: 'right' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredJobs.map((job) => {
                const totalObjs = job.progress?.objects_total || job.objects_total || 0;
                const processedObjs = job.progress?.objects_processed || job.objects_processed || 0;
                const confidence = job.validation?.structural_confidence;
                const confidencePercent = confidence !== undefined ? Math.round(confidence * 100) : null;

                return (
                  <tr
                    key={job.id}
                    style={{ cursor: 'pointer' }}
                    onClick={() => navigate(`/jobs/${job.id}`)}
                  >
                    <td>
                      <div style={{ fontWeight: 600, color: 'var(--ink)' }}>{job.name}</div>
                      <div
                        style={{
                          fontSize: '0.6875rem',
                          color: 'var(--ink-3)',
                          fontFamily: 'var(--font-mono)',
                          marginTop: '2px',
                        }}
                      >
                        {job.id}
                      </div>
                    </td>

                    <td>
                      <StatusBadge status={job.status} size="sm" />
                    </td>

                    <td>
                      <span className="tool-chip" style={{ fontSize: '0.6875rem' }}>
                        {job.progress?.current_stage || job.current_stage || 'DISCOVERY'}
                      </span>
                    </td>

                    <td>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                        <span
                          style={{
                            fontSize: '0.75rem',
                            fontFamily: 'var(--font-mono)',
                            color: 'var(--ink)',
                          }}
                        >
                          {processedObjs} / {totalObjs > 0 ? totalObjs : '—'}
                        </span>
                        {totalObjs > 0 && (
                          <div
                            style={{
                              width: '100px',
                              height: '4px',
                              background: 'var(--field)',
                              borderRadius: 'var(--radius-full)',
                              overflow: 'hidden',
                            }}
                          >
                            <div
                              style={{
                                height: '100%',
                                width: `${Math.min(100, Math.round((processedObjs / totalObjs) * 100))}%`,
                                background: 'var(--primary)',
                              }}
                            />
                          </div>
                        )}
                      </div>
                    </td>

                    <td>
                      {confidencePercent !== null ? (
                        <span
                          style={{
                            fontFamily: 'var(--font-mono)',
                            fontSize: '0.8125rem',
                            fontWeight: 700,
                            color:
                              confidencePercent >= 95
                                ? 'var(--green)'
                                : confidencePercent >= 85
                                  ? 'var(--yellow)'
                                  : 'var(--red)',
                          }}
                        >
                          {confidencePercent}%
                        </span>
                      ) : (
                        <span style={{ fontSize: '0.75rem', color: 'var(--ink-3)' }}>—</span>
                      )}
                    </td>

                    <td style={{ fontSize: '0.75rem', color: 'var(--ink-2)' }}>
                      {new Date(job.created_at).toLocaleDateString('en-US', {
                        month: 'short',
                        day: 'numeric',
                        hour: '2-digit',
                        minute: '2-digit',
                      })}
                    </td>

                    <td style={{ textAlign: 'right' }}>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          navigate(`/jobs/${job.id}`);
                        }}
                        className="btn btn-ghost"
                        style={{ padding: '6px' }}
                        title="Open migration control center"
                      >
                        <ArrowRight size={16} />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
