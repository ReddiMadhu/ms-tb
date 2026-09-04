import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  Download,
  FileSpreadsheet,
  Database,
  FileCode,
  FolderTree,
  RefreshCw,
  AlertCircle,
} from 'lucide-react';
import { api, type ArtifactItem, type Job } from '../api';
import { TableauIcon } from '../components/icons/TableauIcon';
import { ExcelIcon } from '../components/icons/ExcelIcon';

export default function ExportCenter() {
  const { jobId } = useParams<{ jobId: string }>();
  const [job, setJob] = useState<Job | null>(null);
  const [artifacts, setArtifacts] = useState<ArtifactItem[]>([]);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  const loadExportData = React.useCallback(async () => {
    if (!jobId) return;
    try {
      const res = await api.listArtifacts(jobId);
      const raw = res.artifacts || [];
      const hasProdWb = raw.some((a) => a.environment === 'production' || (a.file_name || '').includes('_prod'));
      const filtered = hasProdWb
        ? raw.filter((a) => !(a.environment === 'staging' && (a.file_name || '').endsWith('.twbx')))
        : raw;
      setArtifacts(filtered);
    } catch {
      // Keep existing artifacts on error
    }

    try {
      const j = await api.getJob(jobId);
      setJob(j);
    } catch {
      // Keep existing job
    }
  }, [jobId]);

  useEffect(() => {
    loadExportData();
  }, [loadExportData]);

  const handleDownloadArtifact = async (art: ArtifactItem) => {
    if (!jobId) return;
    setDownloadingId(art.id);
    setDownloadError(null);
    try {
      await api.downloadArtifact(jobId, art.id, art.file_name);
    } catch (err: any) {
      setDownloadError(`Failed to download ${art.file_name}: ${err?.message || 'Network error'}`);
    } finally {
      setDownloadingId(null);
    }
  };

  const handleDownloadExcel = async () => {
    if (!jobId) return;
    setDownloadingId('excel');
    setDownloadError(null);
    try {
      await api.downloadExcelReport(jobId, job?.name);
    } catch (err: any) {
      setDownloadError(`Failed to download Excel documentation: ${err?.message || 'Server error'}`);
    } finally {
      setDownloadingId(null);
    }
  };

  const totalArtifactsCount = artifacts.length + 1;

  return (
    <div style={{ maxWidth: '1440px', margin: '0 auto' }}>
      {/* ── Header / Section Title ────────────────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px', marginBottom: '16px', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <FolderTree size={18} color="var(--primary, #6366f1)" />
          <h3 style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--ink)', margin: 0 }}>
            Artifact Explorer
          </h3>
          <span style={{
            fontSize: '0.75rem',
            fontWeight: 700,
            color: 'var(--primary, #6366f1)',
            background: 'var(--primary-tint, rgba(99, 102, 241, 0.12))',
            padding: '2px 8px',
            borderRadius: 'var(--radius-full)',
          }}>
            {totalArtifactsCount}
          </span>
        </div>
      </div>

      {/* ── Error Notification ──────────────────────────────────── */}
      {downloadError && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            padding: '12px 16px',
            borderRadius: 'var(--radius-md)',
            background: 'rgba(239, 68, 68, 0.1)',
            border: '1px solid rgba(239, 68, 68, 0.3)',
            color: '#ef4444',
            fontSize: '0.8125rem',
            marginBottom: '16px',
          }}
        >
          <AlertCircle size={16} style={{ flexShrink: 0 }} />
          <span style={{ flex: 1 }}>{downloadError}</span>
          <button
            type="button"
            onClick={() => setDownloadError(null)}
            style={{
              background: 'none',
              border: 'none',
              color: '#ef4444',
              cursor: 'pointer',
              fontWeight: 700,
              fontSize: '0.875rem',
            }}
          >
            ✕
          </button>
        </div>
      )}

      {/* ── Artifact Cards Grid ───────────────────────────────────── */}
      <div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))', gap: '16px' }}>
          {artifacts.map((art) => {
            const isTwbx = (art.file_name || '').endsWith('.twbx');
            const isHyper = (art.file_name || '').endsWith('.hyper');

            return (
              <div
                key={art.id}
                style={{
                  background: 'var(--surface)',
                  border: '1px solid var(--line)',
                  borderRadius: 'var(--radius-lg)',
                  padding: '20px',
                  boxShadow: 'var(--shadow-card)',
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: 'space-between',
                  gap: '16px',
                }}
              >
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                      <div style={{
                        width: '36px', height: '36px', borderRadius: 'var(--radius-sm)',
                        background: 'var(--field)', display: 'flex', alignItems: 'center', justifyContent: 'center',
                        color: isTwbx ? 'var(--primary)' : isHyper ? 'var(--green)' : 'var(--blue)',
                      }}>
                        {isTwbx ? <TableauIcon size={20} /> : isHyper ? <Database size={18} /> : <FileCode size={18} />}
                      </div>
                      <div>
                        <h4 style={{ fontSize: '0.9375rem', fontWeight: 700, color: 'var(--ink)', margin: 0 }}>
                          {art.file_name}
                        </h4>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '4px' }}>
                          <span className="tool-chip mono" style={{ fontSize: '0.6875rem' }}>
                            {art.type}
                          </span>
                        </div>
                      </div>
                    </div>
                  </div>

                  <p style={{ fontSize: '0.8125rem', color: 'var(--ink-2)', margin: 0, lineHeight: 1.5 }}>
                    {isTwbx
                      ? (art.environment === 'production' || art.file_name.includes('_prod'))
                        ? 'Production-ready Tableau packaged workbook configured with production datasource paths for direct server deployment.'
                        : 'Self-contained staging workbook with embedded extracts for local validation & Tableau Desktop verification.'
                      : isHyper
                      ? 'High-performance Hyper extract containing pre-aggregated analytical rows.'
                      : 'Tableau data source definition with calculated field logic & metadata.'}
                  </p>
                </div>

                <div style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  paddingTop: '12px', borderTop: '1px solid var(--line)',
                }}>
                  <span className="mono" style={{ fontSize: '0.75rem', color: 'var(--ink-3)' }}>
                    {art.size_bytes ? `${Math.round(art.size_bytes / 1024)} KB` : '42 KB'}
                  </span>

                  <button
                    type="button"
                    onClick={() => handleDownloadArtifact(art)}
                    disabled={downloadingId !== null}
                    className="btn btn-primary"
                    style={{
                      padding: '6px 12px',
                      fontSize: '0.75rem',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '4px',
                      cursor: downloadingId !== null ? 'not-allowed' : 'pointer',
                      opacity: downloadingId !== null && downloadingId !== art.id ? 0.6 : 1,
                    }}
                  >
                    {downloadingId === art.id ? (
                      <>
                        <RefreshCw size={13} className="animate-spin" /> Downloading...
                      </>
                    ) : (
                      <>
                        <Download size={13} /> Download
                      </>
                    )}
                  </button>
                </div>
              </div>
            );
          })}

          {/* ── Complete Migration Documentation (.xlsx) ── */}
          <div
            style={{
              background: 'var(--surface)',
              border: '1px solid var(--line)',
              borderRadius: 'var(--radius-lg)',
              padding: '20px',
              boxShadow: 'var(--shadow-card)',
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'space-between',
              gap: '16px',
            }}
          >
            <div>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <div
                    style={{
                      width: '36px',
                      height: '36px',
                      borderRadius: 'var(--radius-sm)',
                      background: 'var(--field)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      color: 'var(--primary)',
                    }}
                  >
                    <ExcelIcon size={20} />
                  </div>
                  <div>
                    <h4 style={{ fontSize: '0.9375rem', fontWeight: 700, color: 'var(--ink)', margin: 0 }}>
                      {job?.name ? `${job.name}_Documentation.xlsx` : 'Complete Migration Documentation.xlsx'}
                    </h4>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '4px' }}>
                      <span className="tool-chip mono" style={{ fontSize: '0.6875rem' }}>
                        documentation
                      </span>
                    </div>
                  </div>
                </div>
              </div>

              <p style={{ fontSize: '0.8125rem', color: 'var(--ink-2)', margin: 0, lineHeight: 1.5 }}>
                Comprehensive extraction &amp; translation report: Overview &amp; KPIs, MSTR Source Metadata, Metric &amp; Logic Translation Matrix, Visual &amp; Worksheet Mapping, and Execution Audit Trail.
              </p>
            </div>

            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                paddingTop: '12px',
                borderTop: '1px solid var(--line)',
              }}
            >
              <span className="mono" style={{ fontSize: '0.75rem', color: 'var(--ink-3)' }}>
                65 KB
              </span>

              <button
                type="button"
                onClick={handleDownloadExcel}
                disabled={downloadingId !== null}
                className="btn btn-primary"
                style={{
                  padding: '6px 12px',
                  fontSize: '0.75rem',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '4px',
                  cursor: downloadingId !== null ? 'not-allowed' : 'pointer',
                  opacity: downloadingId !== null && downloadingId !== 'excel' ? 0.6 : 1,
                }}
              >
                {downloadingId === 'excel' ? (
                  <>
                    <RefreshCw size={13} className="animate-spin" /> Downloading...
                  </>
                ) : (
                  <>
                    <Download size={13} /> Download
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
