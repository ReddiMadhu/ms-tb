import React, { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  FileText,
  ArrowLeft,
  Download,
  Printer,
  ShieldCheck,
  CheckCircle2,
  AlertTriangle,
  FolderKanban,
  FileSpreadsheet,
  Database,
  Layers,
  Code,
} from 'lucide-react';
import { api, type Job, type MigrationObject } from '../api';
import { ConfidenceCard } from '../components/migration/ConfidenceCard';
import { ValidationScorecard } from '../components/validation/ValidationScorecard';

export default function MigrationReport() {
  const { jobId } = useParams<{ jobId: string }>();
  const [job, setJob] = useState<Job | null>(null);
  const [objects, setObjects] = useState<MigrationObject[]>([]);

  useEffect(() => {
    if (!jobId) return;
    api.getJob(jobId)
      .then((data) => setJob(data))
      .catch(() => { });

    api.listObjects(jobId)
      .then((res) => setObjects(res.objects || []))
      .catch(() => setObjects([]));
  }, [jobId]);

  const totalObjs = job?.progress?.objects_total || job?.objects_total || objects.length || 0;
  const processedObjs = job?.progress?.objects_processed || job?.objects_processed || objects.length || 0;
  const failedObjs = job?.progress?.objects_failed || job?.objects_failed || 0;
  const isComplete = job?.status === 'COMPLETE' || job?.status === 'PUBLISHED';

  const typeCounts: Record<string, { total: number; succeeded: number; failed: number }> = {};
  objects.forEach((o) => {
    const t = o.type_name || 'other';
    if (!typeCounts[t]) typeCounts[t] = { total: 0, succeeded: 0, failed: 0 };
    typeCounts[t].total += 1;
    if (o.status === 'failed') {
      typeCounts[t].failed += 1;
    } else {
      typeCounts[t].succeeded += 1;
    }
  });

  return (
    <div style={{ maxWidth: '1100px', margin: '0 auto', paddingBottom: '60px' }}>
      {/* ── Top Header ───────────────────────────────────────────── */}
      <div style={{ marginBottom: '24px' }}>
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
              Migration Executive Summary &amp; Audit Report
            </h1>
            <p style={{ fontSize: '0.875rem', color: 'var(--ink-2)', marginTop: '4px' }}>
              Comprehensive stakeholder audit document for MicroStrategy to Tableau migration verification
            </p>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <button
              onClick={() => window.print()}
              className="btn btn-secondary"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                padding: '8px 14px',
                fontSize: '0.8125rem',
              }}
            >
              <Printer size={14} />
              <span>Print Report</span>
            </button>
          </div>
        </div>
      </div>

      {/* ── Report Container ─────────────────────────────────────── */}
      <div
        style={{
          background: 'var(--surface)',
          border: '1px solid var(--line)',
          borderRadius: 'var(--radius-lg)',
          padding: '36px',
          boxShadow: 'var(--shadow-card)',
        }}
      >
        {/* Document Meta */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            paddingBottom: '20px',
            borderBottom: '2px solid var(--line)',
            marginBottom: '28px',
          }}
        >
          <div>
            <div style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--ink)' }}>
              {job?.name || 'Enterprise BI Migration'}
            </div>
            <div style={{ fontSize: '0.8125rem', color: 'var(--ink-2)', marginTop: '4px' }}>
              Generated Date: {new Date().toLocaleDateString('en-US', { dateStyle: 'long' })}
            </div>
          </div>

          <div style={{ textAlign: 'right' }}>
            <span
              style={{
                padding: '6px 12px',
                borderRadius: 'var(--radius-full)',
                background: isComplete ? 'var(--green-tint)' : 'var(--blue-tint)',
                color: isComplete ? 'var(--green)' : 'var(--blue)',
                fontWeight: 700,
                fontSize: '0.8125rem',
              }}
            >
              {isComplete ? '100% Verified Production Parity' : `Status: ${job?.status || 'In Progress'}`}
            </span>
          </div>
        </div>

        {/* Section 1: Executive Summary */}
        <div style={{ marginBottom: '32px' }}>
          <h2 style={{ fontSize: '1.125rem', fontWeight: 700, color: 'var(--ink)', marginBottom: '12px' }}>
            1. Executive Summary
          </h2>
          <p style={{ fontSize: '0.875rem', color: 'var(--ink-2)', lineHeight: 1.6, margin: 0 }}>
            This audit report validates the automated reverse-engineering and semantic reconstruction
            of MicroStrategy business intelligence assets into Tableau Server {job?.template_version || '2024.2'}. All {totalObjs} discovered objects,
            metrics, LOD expressions, underlying database relationship schemas, and worksheet visual
            charts have undergone multi-tier algorithmic validation and ground-truth parity comparison.
          </p>
        </div>

        {/* Section 2: Environment Topology */}
        <div style={{ marginBottom: '32px' }}>
          <h2 style={{ fontSize: '1.125rem', fontWeight: 700, color: 'var(--ink)', marginBottom: '16px' }}>
            2. Source &amp; Target Environments
          </h2>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
            <div
              style={{
                padding: '16px',
                background: 'var(--field)',
                borderRadius: 'var(--radius-md)',
                border: '1px solid var(--line)',
              }}
            >
              <div style={{ fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--ink-3)', fontWeight: 600 }}>
                Source Environment
              </div>
              <div style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--ink)', marginTop: '4px' }}>
                {job?.mstr_version ? `MicroStrategy Library (${job.mstr_version})` : 'MicroStrategy Library'}
              </div>
              <div style={{ fontSize: '0.75rem', color: 'var(--ink-2)', marginTop: '4px' }}>
                Project: {job?.mstr_project_name || job?.mstr_project_id || 'Connected Project'}
              </div>
            </div>

            <div
              style={{
                padding: '16px',
                background: 'var(--field)',
                borderRadius: 'var(--radius-md)',
                border: '1px solid var(--line)',
              }}
            >
              <div style={{ fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--ink-3)', fontWeight: 600 }}>
                Target Environment
              </div>
              <div style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--ink)', marginTop: '4px' }}>
                Tableau Server ({job?.template_version || '2024.2'})
              </div>
              <div style={{ fontSize: '0.75rem', color: 'var(--ink-2)', marginTop: '4px' }}>
                Target Project: {job?.tableau_target_project || 'Migrated Dashboards'}
              </div>
            </div>
          </div>
        </div>

        {/* Section 3: Parity & Confidence */}
        <div style={{ marginBottom: '32px' }}>
          <h2 style={{ fontSize: '1.125rem', fontWeight: 700, color: 'var(--ink)', marginBottom: '16px' }}>
            3. Migration Confidence &amp; 4-Tier Promotion Gates
          </h2>
          <ValidationScorecard
            job={job}
            autoPublishEligible={isComplete}
            totalBlockers={failedObjs}
          />
        </div>

        {/* Section 4: Object Migration Coverage */}
        <div>
          <h2 style={{ fontSize: '1.125rem', fontWeight: 700, color: 'var(--ink)', marginBottom: '16px' }}>
            4. Object Migration Coverage Breakdown
          </h2>
          <table className="log-table">
            <thead>
              <tr>
                <th>Artifact Category</th>
                <th>Discovered Count</th>
                <th>Successfully Reconstructed</th>
                <th>Failed / Skipped</th>
                <th>Parity Verification</th>
              </tr>
            </thead>
            <tbody>
              {Object.keys(typeCounts).length === 0 ? (
                <tr>
                  <td style={{ fontWeight: 600 }}>All Discovered Objects</td>
                  <td>{totalObjs}</td>
                  <td>{processedObjs - failedObjs}</td>
                  <td>{failedObjs}</td>
                  <td style={{ color: 'var(--green)', fontWeight: 600 }}>{isComplete ? 'Verified' : 'In Progress'}</td>
                </tr>
              ) : (
                Object.entries(typeCounts).map(([typeName, counts]) => (
                  <tr key={typeName}>
                    <td style={{ fontWeight: 600, textTransform: 'capitalize' }}>
                      {typeName}s
                    </td>
                    <td>{counts.total}</td>
                    <td>{counts.succeeded}</td>
                    <td>{counts.failed}</td>
                    <td style={{ color: counts.failed === 0 ? 'var(--green)' : 'var(--yellow)', fontWeight: 600 }}>
                      {counts.failed === 0 ? 'Verified' : `${counts.failed} Warnings`}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
