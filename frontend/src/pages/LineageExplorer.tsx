import React, { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  GitBranch,
  ArrowLeft,
  Search,
  Database,
  Layers,
  FileSpreadsheet,
  ArrowRight,
  ExternalLink,
  ChevronRight,
} from 'lucide-react';
import { api, type CrossReferenceMapping } from '../api';
import { EmptyState } from '../components/ui/EmptyState';

export default function LineageExplorer() {
  const { jobId } = useParams<{ jobId: string }>();
  const [mappings, setMappings] = useState<CrossReferenceMapping[]>([]);
  const [search, setSearch] = useState('');

  useEffect(() => {
    api.getCrossReference({ job_id: jobId })
      .then((res) => {
        if (res.mappings && res.mappings.length > 0) {
          setMappings(res.mappings);
        } else if (jobId) {
          api.listObjects(jobId).then((objRes) => {
            const mapped: CrossReferenceMapping[] = (objRes.objects || []).map((o) => ({
              mstr_id: o.mstr_id,
              mstr_name: o.name,
              mstr_type: o.type_name || 'object',
              mstr_path: o.mstr_path || '/Public Objects/',
              tableau_workbook_id: o.cross_reference?.tableau_workbook_id || `wb-${jobId.slice(0, 8)}`,
              tableau_workbook_name: 'Target Tableau Model',
              tableau_datasource_id: o.cross_reference?.tableau_datasource_id || `ds-${jobId.slice(0, 8)}`,
              tableau_field_name: o.tableau_calc || o.name,
              tableau_field_type: o.type_name === 'metric' ? 'measure' : 'dimension',
              job_id: o.job_id,
              migrated_at: new Date().toISOString(),
            }));
            setMappings(mapped);
          });
        }
      })
      .catch(() => {
        setMappings([]);
      });
  }, [jobId]);

  const filtered = mappings.filter((m) =>
    m.mstr_name.toLowerCase().includes(search.toLowerCase()) ||
    m.tableau_workbook_name.toLowerCase().includes(search.toLowerCase()) ||
    m.tableau_field_name.toLowerCase().includes(search.toLowerCase())
  );

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
              Lineage &amp; Cross-Reference Explorer
            </h1>
            <p style={{ fontSize: '0.875rem', color: 'var(--ink-2)', marginTop: '4px' }}>
              Trace end-to-end data flow from source tables and MSTR metrics to target Tableau workbooks and datasources
            </p>
          </div>
        </div>
      </div>

      {/* ── Visual Lineage Pipeline Flow Diagram ─────────────────── */}
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
        <h3 style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--ink)', marginBottom: '16px' }}>
          Interactive Data Lineage Map
        </h3>

        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '12px',
            overflowX: 'auto',
            paddingBottom: '8px',
          }}
        >
          {[
            { step: '1. Source Warehouse Table', desc: 'SQL Server / Oracle DW', icon: Database },
            { step: '2. MSTR Semantic Attribute & Metric', desc: 'Facts, Dimty & Expressions', icon: Layers },
            { step: '3. BI-IR Intermediate Compilation', desc: 'Universal BI AST representation', icon: GitBranch },
            { step: '4. Tableau Hyper Data Extract', desc: 'Single & Multi-table extracts', icon: Database },
            { step: '5. Tableau Target Workbook', desc: 'Worksheets & Dashboards', icon: FileSpreadsheet },
          ].map((item, idx, arr) => {
            const Icon = item.icon;
            const isLast = idx === arr.length - 1;
            return (
              <React.Fragment key={idx}>
                <div
                  style={{
                    flex: 1,
                    minWidth: '180px',
                    padding: '16px',
                    background: 'var(--field)',
                    borderRadius: 'var(--radius-md)',
                    border: '1px solid var(--line)',
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'flex-start',
                    gap: '8px',
                  }}
                >
                  <div
                    style={{
                      width: '32px',
                      height: '32px',
                      borderRadius: 'var(--radius-sm)',
                      background: 'var(--surface)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      color: 'var(--primary)',
                    }}
                  >
                    <Icon size={16} />
                  </div>
                  <div>
                    <div style={{ fontSize: '0.8125rem', fontWeight: 600, color: 'var(--ink)' }}>
                      {item.step}
                    </div>
                    <div style={{ fontSize: '0.6875rem', color: 'var(--ink-3)', marginTop: '2px' }}>
                      {item.desc}
                    </div>
                  </div>
                </div>

                {!isLast && (
                  <div style={{ color: 'var(--ink-3)', flexShrink: 0 }}>
                    <ChevronRight size={18} />
                  </div>
                )}
              </React.Fragment>
            );
          })}
        </div>
      </div>

      {/* ── Search & Cross-Reference Table ───────────────────────── */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: '16px',
        }}
      >
        <h3 style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--ink)', margin: 0 }}>
          Direct Cross-Reference Table ({filtered.length} Mappings)
        </h3>

        <div className="search-bar" style={{ minWidth: '300px' }}>
          <Search size={16} className="search-icon" />
          <input
            type="text"
            className="input"
            placeholder="Search lineage by source or target name..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

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
              <th>MicroStrategy Source Object</th>
              <th>MSTR Type</th>
              <th>Target Tableau Field</th>
              <th>Field Type</th>
              <th>Target Workbook</th>
              <th>Target Datasource</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((m, idx) => (
              <tr key={idx}>
                <td style={{ fontWeight: 600, color: 'var(--ink)' }}>{m.mstr_name}</td>
                <td>
                  <span className="tool-chip" style={{ textTransform: 'capitalize' }}>
                    {m.mstr_type}
                  </span>
                </td>
                <td
                  style={{
                    fontFamily: 'var(--font-mono)',
                    color: 'var(--primary)',
                    fontWeight: 600,
                  }}
                >
                  {m.tableau_field_name}
                </td>
                <td style={{ textTransform: 'capitalize', color: 'var(--ink-2)' }}>
                  {m.tableau_field_type}
                </td>
                <td style={{ color: 'var(--ink)' }}>{m.tableau_workbook_name}</td>
                <td className="mono" style={{ fontSize: '0.75rem', color: 'var(--ink-3)' }}>
                  {m.tableau_datasource_id}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
