import React, { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  Download,
  FileSpreadsheet,
  Database,
  FileText,
  CheckCircle2,
  Rocket,
  FileCode,
  Code2,
  Copy,
  Check,
  FolderTree,
} from 'lucide-react';
import { api, type ArtifactItem, type Job } from '../api';

export default function ExportCenter() {
  const { jobId } = useParams<{ jobId: string }>();
  const [job, setJob] = useState<Job | null>(null);
  const [artifacts, setArtifacts] = useState<ArtifactItem[]>([]);
  const [activeTab, setActiveTab] = useState<'ARTIFACTS' | 'XML_PREVIEW'>('ARTIFACTS');
  const [copiedXml, setCopiedXml] = useState(false);
  const [tdsXml, setTdsXml] = useState<string>('');

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

      // Fetch real TDS XML if available
      const tdsArt = raw.find((a) => (a.file_name || '').endsWith('.tds') || a.type === 'datasource');
      if (tdsArt) {
        fetch(`/api/v1/jobs/${jobId}/download/${tdsArt.id}`)
          .then((r) => (r.ok ? r.text() : ''))
          .then((text) => {
            if (text && text.includes('<datasource')) {
              setTdsXml(text);
            }
          })
          .catch(() => {});
      }
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

  const targetProject = job?.tableau_target_project || 'Migrated Dashboards';
  const targetVersion = job?.template_version || '2024.2';

  const copyXml = () => {
    navigator.clipboard.writeText(tdsXml);
    setCopiedXml(true);
    setTimeout(() => setCopiedXml(false), 2000);
  };

  const downloadXml = () => {
    const blob = new Blob([tdsXml], { type: 'application/xml' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'Migrated_DS.tds';
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div style={{ maxWidth: '1440px', margin: '0 auto' }}>
      {/* ── Toolbar: Tab Selector ────────────────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px', marginBottom: '16px', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <button
            onClick={() => setActiveTab('ARTIFACTS')}
            className={`btn ${activeTab === 'ARTIFACTS' ? 'btn-primary' : 'btn-secondary'}`}
            style={{ padding: '6px 14px', fontSize: '0.8125rem', display: 'flex', alignItems: 'center', gap: '6px' }}
          >
            <FolderTree size={15} /> Artifact Explorer ({artifacts.length})
          </button>
          <button
            onClick={() => setActiveTab('XML_PREVIEW')}
            className={`btn ${activeTab === 'XML_PREVIEW' ? 'btn-primary' : 'btn-secondary'}`}
            style={{ padding: '6px 14px', fontSize: '0.8125rem', display: 'flex', alignItems: 'center', gap: '6px' }}
          >
            <Code2 size={15} /> Tableau Datasource XML (.tds)
          </button>
        </div>
      </div>

      {/* ── Tab Content ───────────────────────────────────────────── */}
      {activeTab === 'ARTIFACTS' ? (
        <div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))', gap: '16px' }}>
          {artifacts.map((art) => {
            const isTwbx = (art.file_name || '').endsWith('.twbx');
            const isHyper = (art.file_name || '').endsWith('.hyper');
            const isTds = (art.file_name || '').endsWith('.tds');

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
                        {isTwbx ? <FileSpreadsheet size={18} /> : isHyper ? <Database size={18} /> : <FileCode size={18} />}
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

                  <a
                    href={`/api/v1/jobs/${jobId}/download/${art.id}`}
                    download={art.file_name}
                    className="btn btn-primary"
                    style={{ padding: '6px 12px', fontSize: '0.75rem', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: '4px' }}
                  >
                    <Download size={13} /> Download
                  </a>
                </div>
              </div>
            );
          })}

          {/* ── Card 3: Complete Migration Documentation (.xlsx) ── */}
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
                      background: 'rgba(34, 197, 94, 0.12)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      color: 'var(--green, #22c55e)',
                    }}
                  >
                    <FileSpreadsheet size={18} />
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
                onClick={() => jobId && api.downloadExcelReport(jobId, job?.name)}
                className="btn btn-primary"
                style={{
                  padding: '6px 12px',
                  fontSize: '0.75rem',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '4px',
                  background: 'var(--green, #22c55e)',
                  borderColor: 'var(--green, #22c55e)',
                }}
              >
                <Download size={13} /> Download
              </button>
            </div>
          </div>
          </div>
        </div>
      ) : (
        /* XML Preview Tab */
        <div style={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 'var(--radius-lg)', overflow: 'hidden' }}>
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '12px 16px', borderBottom: '1px solid var(--line)', background: 'var(--field)',
          }}>
            <span style={{ fontSize: '0.8125rem', fontWeight: 600, color: 'var(--ink)' }}>
              Tableau Datasource Specification (.tds XML)
            </span>
            {tdsXml ? (
              <div style={{ display: 'flex', gap: '8px' }}>
                <button onClick={copyXml} className="btn btn-ghost" style={{ padding: '5px 10px', fontSize: '0.75rem', display: 'flex', alignItems: 'center', gap: '4px' }}>
                  {copiedXml ? <><Check size={13} color="var(--green)" /> Copied</> : <><Copy size={13} /> Copy XML</>}
                </button>
                <button onClick={downloadXml} className="btn btn-secondary" style={{ padding: '5px 10px', fontSize: '0.75rem', display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <Download size={13} /> Download .tds
                </button>
              </div>
            ) : null}
          </div>
          {tdsXml ? (
            <pre style={{
              padding: '16px 20px', margin: 0, fontSize: '0.8125rem', lineHeight: '1.65',
              fontFamily: 'var(--font-mono)', color: 'var(--ink)', background: 'var(--field)',
              maxHeight: '550px', overflowY: 'auto', whiteSpace: 'pre-wrap',
            }}>
              {tdsXml}
            </pre>
          ) : (
            <div
              style={{
                padding: '48px 24px',
                textAlign: 'center',
                background: 'var(--field)',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '10px',
              }}
            >
              <FileCode size={32} color="var(--ink-3)" />
              <h4 style={{ fontSize: '0.9375rem', fontWeight: 600, color: 'var(--ink)', margin: 0 }}>
                Tableau Datasource (.tds) XML Not Available Yet
              </h4>
              <p style={{ fontSize: '0.8125rem', color: 'var(--ink-2)', maxWidth: '480px', margin: 0, lineHeight: 1.5 }}>
                Tableau Datasource (.tds) XML is generated during the <strong>DATASOURCE_EMIT</strong> stage. Once generated and staged by the pipeline, you will be able to inspect and download the raw XML specification here.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
