import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  GitBranch,
  Search,
  Database,
  Layers,
  FileSpreadsheet,
  ArrowRight,
  ChevronRight,
  Filter,
  CheckCircle2,
} from 'lucide-react';
import { api, type CrossReferenceMapping, type MigrationObject, type Job } from '../api';

export default function LineageExplorer() {
  const { jobId } = useParams<{ jobId: string }>();
  const [job, setJob] = useState<Job | null>(null);
  const [objects, setObjects] = useState<MigrationObject[]>([]);
  const [mappings, setMappings] = useState<CrossReferenceMapping[]>([]);
  const [search, setSearch] = useState('');
  const [selectedType, setSelectedType] = useState<string>('all');
  const [activeNode, setActiveNode] = useState<string | null>(null);

  useEffect(() => {
    if (!jobId) return;

    api.getJob(jobId).then((j) => setJob(j)).catch(() => {});

    api.listObjects(jobId).then((objRes) => {
      const objs = objRes.objects || [];
      setObjects(objs);

      const mapped: CrossReferenceMapping[] = objs.map((o) => ({
        mstr_id: o.mstr_id,
        mstr_name: o.name,
        mstr_type: o.type_name || 'object',
        mstr_path: o.mstr_path || '/Public Objects/',
        tableau_workbook_id: o.cross_reference?.tableau_workbook_id || 'Marketing Campaigns.twbx',
        tableau_workbook_name: job?.name || 'Marketing Campaigns',
        tableau_datasource_id: o.cross_reference?.tableau_datasource_id || 'Migrated_DS.tds',
        tableau_field_name: o.tableau_calc || (o.type_name === 'metric' ? `SUM([${o.name}])` : `[${o.name}]`),
        tableau_field_type: o.type_name === 'metric' ? 'measure' : 'dimension',
        job_id: o.job_id,
        migrated_at: new Date().toISOString(),
      }));
      setMappings(mapped);
    }).catch(() => {
      setObjects([]);
      setMappings([]);
    });
  }, [jobId]);

  const cubes = objects.filter((o) => o.type_name === 'cube');
  const attributes = objects.filter((o) => o.type_name === 'attribute');
  const metrics = objects.filter((o) => o.type_name === 'metric');
  const dossiers = objects.filter((o) => o.type_name === 'dossier');

  const filtered = mappings.filter((m) => {
    const matchesSearch =
      m.mstr_name.toLowerCase().includes(search.toLowerCase()) ||
      m.tableau_field_name.toLowerCase().includes(search.toLowerCase()) ||
      m.mstr_id.toLowerCase().includes(search.toLowerCase());

    const matchesType =
      selectedType === 'all' ||
      (selectedType === 'attribute' && m.mstr_type === 'attribute') ||
      (selectedType === 'metric' && m.mstr_type === 'metric') ||
      (selectedType === 'cube' && m.mstr_type === 'cube');

    const matchesActiveNode =
      !activeNode ||
      m.mstr_name === activeNode ||
      (activeNode === 'attributes' && m.mstr_type === 'attribute') ||
      (activeNode === 'metrics' && m.mstr_type === 'metric') ||
      (activeNode === 'cube' && m.mstr_type === 'cube');

    return matchesSearch && matchesType && matchesActiveNode;
  });

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
              Interactive Data Lineage &amp; Entity Mapping ({mappings.length} Items)
            </h2>
          </div>

          {activeNode && (
            <button
              onClick={() => setActiveNode(null)}
              className="btn btn-ghost"
              style={{ fontSize: '0.75rem', padding: '4px 8px' }}
            >
              Reset Active Lineage Focus
            </button>
          )}
        </div>
      </div>

      {/* ── Real Interactive Multi-Tier Lineage Flow Graph ───────── */}
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
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
          <h3 style={{ fontSize: '0.9375rem', fontWeight: 600, color: 'var(--ink)', margin: 0 }}>
            Source-to-Target Object Hierarchy
          </h3>
          <span style={{ fontSize: '0.75rem', color: 'var(--ink-3)' }}>
            Click any node to focus downstream mappings
          </span>
        </div>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(4, 1fr)',
            gap: '16px',
            alignItems: 'stretch',
          }}
        >
          {/* Node 1: Source Cube */}
          <div
            onClick={() => setActiveNode(activeNode === 'cube' ? null : 'cube')}
            style={{
              padding: '16px',
              background: activeNode === 'cube' ? 'var(--blue-tint)' : 'var(--field)',
              border: `1px solid ${activeNode === 'cube' ? 'var(--blue)' : 'var(--line)'}`,
              borderRadius: 'var(--radius-md)',
              cursor: 'pointer',
              transition: 'all 0.2s ease',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
              <Database size={16} color="var(--blue)" />
              <span style={{ fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase', color: 'var(--ink-3)' }}>
                1. Source MSTR Cube
              </span>
            </div>
            <div style={{ fontSize: '0.9375rem', fontWeight: 700, color: 'var(--ink)' }}>
              {cubes[0]?.name || 'A.Marketing_Campaign_AI_M'}
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--ink-2)', marginTop: '4px' }}>
              {attributes.length} Attributes &bull; {metrics.length} Measures
            </div>
          </div>

          {/* Node 2: Extracted Attributes & Schema */}
          <div
            onClick={() => setActiveNode(activeNode === 'attributes' ? null : 'attributes')}
            style={{
              padding: '16px',
              background: activeNode === 'attributes' ? 'var(--primary-tint, rgba(255,100,50,0.1))' : 'var(--field)',
              border: `1px solid ${activeNode === 'attributes' ? 'var(--primary)' : 'var(--line)'}`,
              borderRadius: 'var(--radius-md)',
              cursor: 'pointer',
              transition: 'all 0.2s ease',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
              <Layers size={16} color="var(--primary)" />
              <span style={{ fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase', color: 'var(--ink-3)' }}>
                2. Dimensions &amp; Attributes
              </span>
            </div>
            <div style={{ fontSize: '0.9375rem', fontWeight: 700, color: 'var(--ink)' }}>
              {attributes.length} Extracted Attributes
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--ink-2)', marginTop: '4px' }}>
              Campaign, Article, Date, Category
            </div>
          </div>

          {/* Node 3: Calculated Measures */}
          <div
            onClick={() => setActiveNode(activeNode === 'metrics' ? null : 'metrics')}
            style={{
              padding: '16px',
              background: activeNode === 'metrics' ? 'var(--green-tint)' : 'var(--field)',
              border: `1px solid ${activeNode === 'metrics' ? 'var(--green)' : 'var(--line)'}`,
              borderRadius: 'var(--radius-md)',
              cursor: 'pointer',
              transition: 'all 0.2s ease',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
              <GitBranch size={16} color="var(--green)" />
              <span style={{ fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase', color: 'var(--ink-3)' }}>
                3. Measures &amp; Calculations
              </span>
            </div>
            <div style={{ fontSize: '0.9375rem', fontWeight: 700, color: 'var(--ink)' }}>
              {metrics.length} Reconstructed Measures
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--ink-2)', marginTop: '4px' }}>
              Direct Visits, Views, Paid Clicks, Ratios
            </div>
          </div>

          {/* Node 4: Target Tableau Workbook & TDS */}
          <div
            style={{
              padding: '16px',
              background: 'var(--field)',
              border: '1px solid var(--line)',
              borderRadius: 'var(--radius-md)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
              <FileSpreadsheet size={16} color="var(--primary)" />
              <span style={{ fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase', color: 'var(--ink-3)' }}>
                4. Target Tableau Artifacts
              </span>
            </div>
            <div style={{ fontSize: '0.9375rem', fontWeight: 700, color: 'var(--ink)' }}>
              {dossiers[0]?.name || job?.name || 'Marketing Campaigns.twbx'}
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--green)', fontWeight: 600, marginTop: '4px' }}>
              Migrated_DS.tds &bull; Ready for Publish
            </div>
          </div>
        </div>
      </div>

      {/* ── Search & Filter Controls ─────────────────────────────── */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: '16px',
          gap: '16px',
          flexWrap: 'wrap',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {[
            { id: 'all', label: `All (${mappings.length})` },
            { id: 'attribute', label: `Attributes (${attributes.length})` },
            { id: 'metric', label: `Measures (${metrics.length})` },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setSelectedType(tab.id)}
              className={`btn ${selectedType === tab.id ? 'btn-primary' : 'btn-secondary'}`}
              style={{ padding: '6px 12px', fontSize: '0.75rem' }}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div className="search-bar" style={{ minWidth: '280px' }}>
          <Search size={15} className="search-icon" />
          <input
            type="text"
            className="input"
            placeholder="Search lineage by field or GUID..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      {/* ── Cross-Reference Lineage Table ────────────────────────── */}
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
              <th>MSTR GUID</th>
              <th>Type</th>
              <th>Target Tableau Expression</th>
              <th>Target Datasource</th>
              <th>Target Workbook</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={6} style={{ textAlign: 'center', padding: '32px', color: 'var(--ink-3)' }}>
                  No lineage mappings found matching current filter.
                </td>
              </tr>
            ) : (
              filtered.map((m, idx) => (
                <tr key={idx}>
                  <td style={{ fontWeight: 600, color: 'var(--ink)' }}>{m.mstr_name}</td>
                  <td className="mono" style={{ fontSize: '0.6875rem', color: 'var(--ink-3)' }}>
                    {m.mstr_id}
                  </td>
                  <td>
                    <span className="tool-chip" style={{ textTransform: 'capitalize' }}>
                      {m.mstr_type}
                    </span>
                  </td>
                  <td
                    style={{
                      fontFamily: 'var(--font-mono)',
                      color: m.mstr_type === 'metric' ? 'var(--primary)' : 'var(--ink)',
                      fontWeight: 600,
                      fontSize: '0.8125rem',
                    }}
                  >
                    {m.tableau_field_name}
                  </td>
                  <td className="mono" style={{ fontSize: '0.75rem', color: 'var(--ink-2)' }}>
                    {m.tableau_datasource_id}
                  </td>
                  <td style={{ color: 'var(--ink)', fontSize: '0.8125rem' }}>
                    {m.tableau_workbook_id}
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
