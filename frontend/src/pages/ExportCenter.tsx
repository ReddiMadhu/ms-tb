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

  useEffect(() => {
    if (!jobId) return;
    api.listArtifacts(jobId)
      .then((res) => {
        const raw = res.artifacts || [];
        const hasProdWb = raw.some((a) => a.environment === 'production' || (a.file_name || '').includes('_prod'));
        const filtered = hasProdWb
          ? raw.filter((a) => !(a.environment === 'staging' && (a.file_name || '').endsWith('.twbx')))
          : raw;
        setArtifacts(filtered);
      })
      .catch(() => setArtifacts([]));
    api.getJob(jobId).then((j) => setJob(j)).catch(() => setJob(null));
  }, [jobId]);

  const targetProject = job?.tableau_target_project || 'Migrated Dashboards';
  const targetVersion = job?.template_version || '2024.2';

  const mockTdsXml = `<?xml version='1.0' encoding='utf-8' ?>
<datasource formatted-name='Migrated_DS' inline='true' version='18.1' xmlns:user='http://www.tableausoftware.com/xml/user'>
  <document-location>
    <connection-info class='hyper' filename='Migrated_DS.hyper' table='Extract' />
  </document-location>
  <!-- Schema Mappings from MicroStrategy Cube -->
  <column caption='Campaign' datatype='string' name='[Campaign]' role='dimension' type='nominal' />
  <column caption='Article Name' datatype='string' name='[Article Name]' role='dimension' type='nominal' />
  <column caption='Date' datatype='date' name='[Date]' role='dimension' type='ordinal' />
  <column caption='Direct Visits' datatype='integer' name='[Direct Visits]' role='measure' type='quantitative'>
    <calculation class='tableau' formula='SUM([Direct Visits])' />
  </column>
  <column caption='Paid Clicks' datatype='integer' name='[Paid Clicks]' role='measure' type='quantitative'>
    <calculation class='tableau' formula='SUM([Paid Clicks])' />
  </column>
  <column caption='Percent Paid Clicks' datatype='real' name='[Percent Paid Clicks]' role='measure' type='quantitative'>
    <calculation class='tableau' formula='SUM([Paid Clicks]) / NULLIF(SUM([Views]), 0)' />
  </column>
</datasource>`;

  const copyXml = () => {
    navigator.clipboard.writeText(mockTdsXml);
    setCopiedXml(true);
    setTimeout(() => setCopiedXml(false), 2000);
  };

  const downloadXml = () => {
    const blob = new Blob([mockTdsXml], { type: 'application/xml' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'Migrated_DS.tds';
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div style={{ maxWidth: '1440px', margin: '0 auto' }}>
      {/* ── KPI Header Grid (Matching db-tb DeploymentReviewDetail) ─ */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px', marginBottom: '20px' }}>
        <div style={kpiCard}>
          <span style={kpiLabel}>Exportable Artifacts</span>
          <span style={kpiValue}>{artifacts.length} Files</span>
        </div>
        <div style={kpiCard}>
          <span style={kpiLabel}>Target Tableau Version</span>
          <span style={{ ...kpiValue, fontSize: '1.125rem', paddingTop: '4px' }}>Tableau {targetVersion}</span>
        </div>
        <div style={kpiCard}>
          <span style={kpiLabel}>Destination Project</span>
          <span style={{ ...kpiValue, fontSize: '1.125rem', color: 'var(--primary)', paddingTop: '4px' }}>{targetProject}</span>
        </div>
        <div style={kpiCard}>
          <span style={kpiLabel}>Deployment Readiness</span>
          <span style={{ ...kpiValue, color: 'var(--green)' }}>Ready</span>
        </div>
      </div>

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
                          {isTwbx && (
                            <span
                              style={{
                                fontSize: '0.6875rem',
                                fontWeight: 600,
                                padding: '1px 6px',
                                borderRadius: '4px',
                                background: (art.environment === 'production' || art.file_name.includes('_prod'))
                                  ? 'var(--primary-tint, rgba(99, 102, 241, 0.12))'
                                  : 'var(--blue-tint, rgba(0, 168, 204, 0.12))',
                                color: (art.environment === 'production' || art.file_name.includes('_prod'))
                                  ? 'var(--primary, #6366f1)'
                                  : 'var(--blue, #00a8cc)',
                                border: `1px solid ${(art.environment === 'production' || art.file_name.includes('_prod')) ? 'var(--primary, rgba(99, 102, 241, 0.3))' : 'var(--blue, rgba(0, 168, 204, 0.3))'}`,
                              }}
                            >
                              {(art.environment === 'production' || art.file_name.includes('_prod')) ? 'Production Package' : 'Staging / Verification'}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>

                    <span style={{ fontSize: '0.75rem', color: 'var(--green)', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '3px' }}>
                      <CheckCircle2 size={13} /> Generated
                    </span>
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
            <div style={{ display: 'flex', gap: '8px' }}>
              <button onClick={copyXml} className="btn btn-ghost" style={{ padding: '5px 10px', fontSize: '0.75rem', display: 'flex', alignItems: 'center', gap: '4px' }}>
                {copiedXml ? <><Check size={13} color="var(--green)" /> Copied</> : <><Copy size={13} /> Copy XML</>}
              </button>
              <button onClick={downloadXml} className="btn btn-secondary" style={{ padding: '5px 10px', fontSize: '0.75rem', display: 'flex', alignItems: 'center', gap: '4px' }}>
                <Download size={13} /> Download .tds
              </button>
            </div>
          </div>
          <pre style={{
            padding: '16px 20px', margin: 0, fontSize: '0.8125rem', lineHeight: '1.65',
            fontFamily: 'var(--font-mono)', color: 'var(--ink)', background: 'var(--field)',
            maxHeight: '550px', overflowY: 'auto', whiteSpace: 'pre-wrap',
          }}>
            {mockTdsXml}
          </pre>
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
