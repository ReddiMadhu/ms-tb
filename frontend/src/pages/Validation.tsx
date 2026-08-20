import React, { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  ShieldCheck,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  ArrowLeft,
  Filter,
  Search,
  Check,
  RefreshCw,
  ExternalLink,
  ChevronRight,
} from 'lucide-react';
import { api, type ValidationResult, type ValidationCheck, type Job } from '../api';
import { ValidationScorecard } from '../components/validation/ValidationScorecard';
import { ValidationMatrix, type MatrixCategoryItem } from '../components/validation/ValidationMatrix';
import { StatusBadge } from '../components/ui/StatusBadge';
import { EmptyState } from '../components/ui/EmptyState';

export default function Validation() {
  const { jobId } = useParams<{ jobId: string }>();
  const [job, setJob] = useState<Job | null>(null);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [checks, setChecks] = useState<ValidationCheck[]>([]);
  const [selectedCategory, setSelectedCategory] = useState<string | undefined>(undefined);
  const [statusFilter, setStatusFilter] = useState<'all' | 'passed' | 'warnings' | 'failed'>('all');
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!jobId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    Promise.all([
      api.getValidation(jobId).catch(() => null),
      api.getJob(jobId).catch(() => null),
    ]).then(([valData, jobData]) => {
      if (valData) {
        setValidation(valData);
        setChecks(valData.checks || []);
      }
      if (jobData) {
        setJob(jobData);
      }
      setLoading(false);
    });
  }, [jobId]);

  const filteredChecks = checks.filter((c) => {
    const matchesSearch =
      (c.object_name && c.object_name.toLowerCase().includes(search.toLowerCase())) ||
      (c.message && c.message.toLowerCase().includes(search.toLowerCase())) ||
      (c.check_type && c.check_type.toLowerCase().includes(search.toLowerCase()));

    const matchesCategory = !selectedCategory || c.category === selectedCategory;

    const matchesStatus =
      statusFilter === 'all' ||
      (statusFilter === 'passed' && c.passed) ||
      (statusFilter === 'failed' && !c.passed);

    return matchesSearch && matchesCategory && matchesStatus;
  });

  const passedCount = checks.filter((c) => c.passed).length;
  const failedCount = checks.filter((c) => !c.passed).length;
  const isApproved = validation?.auto_publish_ok === true;

  return (
    <div style={{ maxWidth: '1440px', margin: '0 auto' }}>
      {/* ── Header Controls ──────────────────────────────────────── */}
      <div style={{ marginBottom: '16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <h2
              style={{
                fontSize: '1.25rem',
                fontWeight: 700,
                color: 'var(--ink)',
                letterSpacing: '-0.02em',
                margin: 0,
              }}
            >
              Parity Verification &amp; Quality Gates
            </h2>
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                padding: '4px 10px',
                borderRadius: 'var(--radius-full)',
                background: isApproved ? 'var(--green-tint)' : 'var(--yellow-tint)',
                color: isApproved ? 'var(--green)' : 'var(--yellow)',
                fontSize: '0.75rem',
                fontWeight: 700,
              }}
            >
              {isApproved ? <CheckCircle2 size={13} /> : <AlertTriangle size={13} />}
              <span>{isApproved ? 'Auto-Publish Approved' : 'Review Required'}</span>
            </span>
          </div>
        </div>
      </div>

      {/* ── 4-Tier Gate Scorecard ────────────────────────────────── */}
      <ValidationScorecard
        job={job}
        autoPublishEligible={validation?.auto_publish_ok}
        totalBlockers={validation?.blocker_count ?? failedCount}
      />

      {/* ── Validation Matrix (Parity by Functional Area) ────────── */}
      <div style={{ marginBottom: '24px' }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: '12px',
          }}
        >
          <h3 style={{ fontSize: '1.0625rem', fontWeight: 600, color: 'var(--ink)', margin: 0 }}>
            Functional Parity Matrix
          </h3>
          {selectedCategory && (
            <button
              onClick={() => setSelectedCategory(undefined)}
              className="btn btn-ghost"
              style={{ fontSize: '0.75rem', padding: '4px 8px' }}
            >
              Reset Category Filter
            </button>
          )}
        </div>

        <ValidationMatrix
          checks={checks}
          selectedCategoryId={selectedCategory}
          onSelectCategory={(catId) =>
            setSelectedCategory(selectedCategory === catId ? undefined : catId)
          }
        />
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
            { key: 'all', label: `All Checks (${checks.length})` },
            { key: 'passed', label: `Passed (${passedCount})` },
            { key: 'failed', label: `Failed (${failedCount})` },
          ].map((f) => (
            <button
              key={f.key}
              onClick={() => setStatusFilter(f.key as any)}
              style={{
                padding: '6px 14px',
                borderRadius: 'var(--radius-full)',
                border: '1px solid',
                borderColor: statusFilter === f.key ? 'var(--primary)' : 'var(--line)',
                background: statusFilter === f.key ? 'var(--primary-tint)' : 'var(--surface)',
                color: statusFilter === f.key ? 'var(--primary)' : 'var(--ink-2)',
                fontSize: '0.8125rem',
                fontWeight: statusFilter === f.key ? 600 : 500,
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
            placeholder="Search checks by object name, formula, or scenario..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      {/* ── Checks Table ─────────────────────────────────────────── */}
      {filteredChecks.length === 0 ? (
        <EmptyState
          icon={ShieldCheck}
          title="No validation checks match your filter"
          description="Try selecting another category or clearing your search filter."
          actionLabel="Reset Filters"
          onAction={() => {
            setSelectedCategory(undefined);
            setStatusFilter('all');
            setSearch('');
          }}
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
                <th>Status</th>
                <th>Check Type</th>
                <th>Target Object</th>
                <th>Scenario / Dimension Slice</th>
                <th>Expected vs Actual</th>
                <th>Verification Note</th>
              </tr>
            </thead>
            <tbody>
              {filteredChecks.map((c, i) => (
                <tr key={i}>
                  <td>
                    {c.passed ? (
                      <span
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '4px',
                          color: 'var(--green)',
                          fontWeight: 600,
                          fontSize: '0.75rem',
                        }}
                      >
                        <CheckCircle2 size={14} />
                        <span>PASS</span>
                      </span>
                    ) : (
                      <span
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '4px',
                          color: 'var(--red)',
                          fontWeight: 600,
                          fontSize: '0.75rem',
                        }}
                      >
                        <XCircle size={14} />
                        <span>FAIL</span>
                      </span>
                    )}
                  </td>

                  <td>
                    <span className="tool-chip" style={{ fontSize: '0.6875rem' }}>
                      {c.check_type}
                    </span>
                  </td>

                  <td style={{ fontWeight: 600, color: 'var(--ink)' }}>
                    {c.object_name || 'Project Level'}
                  </td>

                  <td
                    style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: '0.75rem',
                      color: 'var(--ink-2)',
                    }}
                  >
                    {c.filter_scenario || 'Default Aggregation'}
                  </td>

                  <td>
                    {c.expected && (
                      <div
                        style={{
                          fontFamily: 'var(--font-mono)',
                          fontSize: '0.75rem',
                          display: 'flex',
                          flexDirection: 'column',
                          gap: '2px',
                        }}
                      >
                        <span style={{ color: 'var(--ink-3)' }}>Exp: {c.expected}</span>
                        <span style={{ color: 'var(--green)', fontWeight: 600 }}>
                          Act: {c.actual}
                        </span>
                      </div>
                    )}
                  </td>

                  <td style={{ fontSize: '0.8125rem', color: 'var(--ink-2)' }}>{c.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
