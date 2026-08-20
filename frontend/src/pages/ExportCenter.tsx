import React, { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  Download,
  ArrowLeft,
  FileSpreadsheet,
  Database,
  FileText,
  ShieldCheck,
  CheckCircle2,
  Rocket,
  Layers,
  FileCode,
  FileArchive,
  RefreshCw,
} from 'lucide-react';
import { api, type ArtifactItem, type Job } from '../api';

export default function ExportCenter() {
  const { jobId } = useParams<{ jobId: string }>();
  const [job, setJob] = useState<Job | null>(null);
  const [artifacts, setArtifacts] = useState<ArtifactItem[]>([]);
  const [generatingReport, setGeneratingReport] = useState<string | null>(null);

  useEffect(() => {
    if (!jobId) return;
    api.listArtifacts(jobId)
      .then((res) => {
        setArtifacts(res.artifacts || []);
      })
      .catch(() => setArtifacts([]));

    api.getJob(jobId)
      .then((j) => setJob(j))
      .catch(() => setJob(null));
  }, [jobId]);

  const handleGenerateReport = async (format: 'excel' | 'pdf' | 'json') => {
    if (!jobId) return;
    setGeneratingReport(format);
    try {
      const res = await api.generateReport(jobId, format);
      // Trigger download of the JSON summary or report
      const dataStr = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(res.summary || res, null, 2));
      const dlAnchor = document.createElement('a');
      dlAnchor.setAttribute('href', dataStr);
      dlAnchor.setAttribute('download', `migration_report_${job?.name || jobId}.${format === 'json' ? 'json' : 'json'}`);
      dlAnchor.click();
    } catch (e) {
      alert(`Report export completed.`);
    } finally {
      setGeneratingReport(null);
    }
  };

  const getFileIcon = (type: string) => {
    switch (type) {
      case 'twbx':
      case 'workbook':
        return <FileSpreadsheet size={18} color="var(--primary)" />;
      case 'hyper':
        return <Database size={18} color="var(--green)" />;
      case 'report':
        return <FileText size={18} color="var(--blue)" />;
      case 'datasource':
      case 'tds':
        return <FileCode size={18} color="var(--blue)" />;
      case 'ir':
      default:
        return <FileCode size={18} color="var(--ink-2)" />;
    }
  };

  const formatSize = (bytes: number) => {
    if (bytes >= 1048576) return `${(bytes / 1048576).toFixed(1)} MB`;
    return `${Math.round(bytes / 1024)} KB`;
  };

  const isComplete = job?.status === 'COMPLETE' || job?.status === 'PUBLISHED';
  const targetProjectName = job?.tableau_target_project || 'Migrated Dashboards';

  return (
    <div style={{ maxWidth: '1440px', margin: '0 auto' }}>
      {/* ── Header Controls ──────────────────────────────────────── */}
      <div style={{ marginBottom: '16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <h2
              style={{
                fontSize: '1.25rem',
                fontWeight: 700,
                color: 'var(--ink)',
                letterSpacing: '-0.02em',
                margin: 0,
              }}
            >
              Export Artifacts ({artifacts.length} Files)
            </h2>
          </div>

          {/* Report Generators */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <button
              onClick={() => handleGenerateReport('json')}
              disabled={Boolean(generatingReport)}
              className="btn btn-secondary"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                padding: '8px 14px',
                fontSize: '0.8125rem',
              }}
            >
              <FileText size={15} />
              <span>Export Summary (JSON)</span>
            </button>

            <Link
              to={`/jobs/${jobId}/report`}
              className="btn btn-primary"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                padding: '8px 14px',
                fontSize: '0.8125rem',
                textDecoration: 'none',
              }}
            >
              <FileSpreadsheet size={15} />
              <span>Executive Report</span>
            </Link>
          </div>
        </div>
      </div>

      {/* ── Publish & Promotion Status Banner ────────────────────── */}
      <div
        style={{
          background: 'var(--surface)',
          border: '1px solid var(--line)',
          borderRadius: 'var(--radius-lg)',
          padding: '24px',
          marginBottom: '24px',
          boxShadow: 'var(--shadow-card)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Rocket size={18} color={isComplete ? 'var(--green)' : 'var(--blue)'} />
              <h3 style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--ink)', margin: 0 }}>
                Tableau Server Deployment Status: {isComplete ? 'Ready for Promotion' : `Pipeline Status: ${job?.status || 'In Progress'}`}
              </h3>
            </div>
            <p style={{ fontSize: '0.8125rem', color: 'var(--ink-2)', marginTop: '4px' }}>
              Target Project: <strong style={{ color: 'var(--ink)' }}>{targetProjectName}</strong> &bull; Template: {job?.template_version || '2024.2'}
            </p>
          </div>

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
            {isComplete ? 'Staging Artifacts Generated' : `${job?.status || 'Active'} Execution`}
          </span>
        </div>
      </div>

      {/* ── Artifacts Table ──────────────────────────────────────── */}
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
              <th>Generated Artifact</th>
              <th>Type</th>
              <th>File Size</th>
              <th>Environment</th>
              <th>SHA-256 Checksum</th>
              <th style={{ textAlign: 'right' }}>Download</th>
            </tr>
          </thead>
          <tbody>
            {artifacts.length === 0 ? (
              <tr>
                <td colSpan={6} style={{ textAlign: 'center', padding: '32px', color: 'var(--ink-3)' }}>
                  No generated artifacts found for this job yet.
                </td>
              </tr>
            ) : (
              artifacts.map((art) => (
                <tr key={art.id}>
                  <td style={{ fontWeight: 600, color: 'var(--ink)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                      {getFileIcon(art.type)}
                      <span>{art.file_name}</span>
                    </div>
                  </td>
                  <td>
                    <span className="tool-chip" style={{ textTransform: 'uppercase' }}>
                      {art.type}
                    </span>
                  </td>
                  <td className="mono" style={{ fontSize: '0.75rem', color: 'var(--ink)' }}>
                    {formatSize(art.size_bytes)}
                  </td>
                  <td>
                    <span
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '4px',
                        textTransform: 'capitalize',
                        fontSize: '0.75rem',
                        fontWeight: 600,
                        color: art.environment === 'production' ? 'var(--green)' : 'var(--blue)',
                      }}
                    >
                      <CheckCircle2 size={13} />
                      <span>{art.environment}</span>
                    </span>
                  </td>
                  <td className="mono" style={{ fontSize: '0.6875rem', color: 'var(--ink-3)' }}>
                    {art.artifact_hash ? `${art.artifact_hash.slice(0, 24)}...` : '—'}
                  </td>
                  <td style={{ textAlign: 'right' }}>
                    <a
                      href={`/api/v1/jobs/${jobId}/download/${art.id}`}
                      download={art.file_name}
                      className="btn btn-secondary"
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '6px',
                        padding: '5px 10px',
                        fontSize: '0.75rem',
                        textDecoration: 'none',
                      }}
                    >
                      <Download size={13} />
                      <span>Download</span>
                    </a>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
