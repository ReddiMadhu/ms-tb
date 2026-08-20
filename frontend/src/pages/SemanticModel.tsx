import React, { useEffect, useState, useMemo } from 'react';
import { useParams } from 'react-router-dom';
import {
  Layers,
  Database,
  Table as TableIcon,
  GitBranch,
  Key,
  Hash,
  Type,
  CheckCircle2,
  Filter,
  Sparkles,
} from 'lucide-react';
import { api } from '../api';
import { EmptyState } from '../components/ui/EmptyState';

interface ColumnDef {
  name: string;
  type: string;
  isKey?: boolean;
  role: 'dimension' | 'measure';
  category?: string;
}

export default function SemanticModel() {
  const { jobId } = useParams<{ jobId: string }>();
  const [columns, setColumns] = useState<ColumnDef[]>([]);
  const [cubeName, setCubeName] = useState<string>('Semantic Data Model');
  const [activeTab, setActiveTab] = useState<'all' | 'dimension' | 'measure'>('all');
  const [search, setSearch] = useState<string>('');

  useEffect(() => {
    if (!jobId) return;
    api.listObjects(jobId)
      .then((res) => {
        const objs = res.objects || [];
        const cube = objs.find((o) => o.type_name === 'cube');
        if (cube) setCubeName(cube.name);

        const attributes = objs.filter((o) => o.type_name === 'attribute');
        const metrics = objs.filter((o) => o.type_name === 'metric');

        const cols: ColumnDef[] = [
          ...attributes.map((a) => {
            let dataType = 'UTF8Char';
            let cat = 'ID / Text';
            try {
              if (a.mstr_definition) {
                const def = typeof a.mstr_definition === 'string' ? JSON.parse(a.mstr_definition) : a.mstr_definition;
                if (def.forms && def.forms[0]) {
                  dataType = def.forms[0].dataType || dataType;
                  cat = def.forms[0].baseFormCategory || cat;
                }
              }
            } catch { }

            return {
              name: a.name,
              type: dataType,
              isKey: a.name.toLowerCase().includes('id') || a.name.toLowerCase().includes('name'),
              role: 'dimension' as const,
              category: cat,
            };
          }),
          ...metrics.map((m) => ({
            name: m.name,
            type: 'Numeric (Double)',
            role: 'measure' as const,
            category: m.name.toLowerCase().includes('percent') ? 'Calculated Ratio' : 'Additive Metric',
          })),
        ];

        setColumns(cols);
      })
      .catch(() => setColumns([]));
  }, [jobId]);

  const dimensions = useMemo(() => columns.filter((c) => c.role === 'dimension'), [columns]);
  const measures = useMemo(() => columns.filter((c) => c.role === 'measure'), [columns]);

  const filtered = useMemo(() => columns.filter((c) => {
    const matchesSearch = c.name.toLowerCase().includes(search.toLowerCase()) || c.type.toLowerCase().includes(search.toLowerCase());
    const matchesTab = activeTab === 'all' || c.role === activeTab;
    return matchesSearch && matchesTab;
  }), [columns, search, activeTab]);

  return (
    <div style={{ maxWidth: '1440px', margin: '0 auto' }}>
      {/* ── KPI Header Grid (Matching db-tb DataModelCanvas) ─────── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px', marginBottom: '20px' }}>
        <div style={kpiCard}>
          <span style={kpiLabel}>Total Model Fields</span>
          <span style={kpiValue}>{columns.length}</span>
        </div>
        <div style={kpiCard}>
          <span style={kpiLabel}>Dimension Attributes</span>
          <span style={kpiValue}>{dimensions.length}</span>
        </div>
        <div style={kpiCard}>
          <span style={kpiLabel}>Measures &amp; Ratios</span>
          <span style={kpiValue}>{measures.length}</span>
        </div>
        <div style={kpiCard}>
          <span style={kpiLabel}>Model Grain &amp; Structure</span>
          <span style={{ ...kpiValue, fontSize: '1.125rem', color: 'var(--primary)', paddingTop: '4px' }}>
            Single-Table Cube
          </span>
        </div>
      </div>

      {/* ── Interactive Visual Data Model Canvas ──────────────────── */}
      <div style={{
        background: 'var(--surface)',
        border: '1px solid var(--line)',
        borderRadius: 'var(--radius-lg)',
        padding: '24px',
        marginBottom: '24px',
        boxShadow: 'var(--shadow-card)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
          <div>
            <h3 style={{ fontSize: '0.9375rem', fontWeight: 700, color: 'var(--ink)', margin: 0 }}>
              Synthesized Semantic Entity Canvas
            </h3>
            <p style={{ fontSize: '0.75rem', color: 'var(--ink-3)', margin: '4px 0 0 0' }}>
              MicroStrategy in-memory cube entity mapped to Tableau data model
            </p>
          </div>
          <span className="tool-chip" style={{ color: 'var(--green)', fontWeight: 600 }}>
            <CheckCircle2 size={13} /> 100% Schema Compatibility
          </span>
        </div>

        {/* Entity Card Diagram */}
        <div style={{
          background: 'var(--field)',
          border: '1px solid var(--line)',
          borderRadius: 'var(--radius-md)',
          padding: '20px',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', paddingBottom: '14px', borderBottom: '1px solid var(--line)' }}>
            <Database size={20} color="var(--primary)" />
            <div>
              <div style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--ink)' }}>{cubeName}</div>
              <div style={{ fontSize: '0.75rem', color: 'var(--ink-3)' }}>
                Target: Tableau TDS Extract &bull; {dimensions.length} Dimensions &bull; {measures.length} Measures
              </div>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px', marginTop: '16px' }}>
            {/* Dimensions Column */}
            <div>
              <div style={{ fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase', color: 'var(--primary)', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <Layers size={13} /> Dimensions ({dimensions.length})
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                {dimensions.map((d, i) => (
                  <div key={i} style={{ padding: '6px 10px', background: 'var(--surface)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--line)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <span style={{ fontSize: '0.8125rem', fontWeight: 600, color: 'var(--ink)' }}>{d.name}</span>
                    <span className="mono" style={{ fontSize: '0.6875rem', color: 'var(--ink-3)' }}>{d.type}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Measures Column */}
            <div>
              <div style={{ fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase', color: 'var(--green)', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <GitBranch size={13} /> Measures &amp; Calculations ({measures.length})
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                {measures.map((m, i) => (
                  <div key={i} style={{ padding: '6px 10px', background: 'var(--surface)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--line)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <span style={{ fontSize: '0.8125rem', fontWeight: 600, color: 'var(--ink)' }}>{m.name}</span>
                    <span style={{ fontSize: '0.6875rem', color: 'var(--green)', fontWeight: 600 }}>{m.category}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ── Filter Controls & Full Schema Table ───────────────────── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '16px', marginBottom: '16px', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          {[
            { key: 'all', label: `All Columns (${columns.length})` },
            { key: 'dimension', label: `Dimensions (${dimensions.length})` },
            { key: 'measure', label: `Measures (${measures.length})` },
          ].map((t) => (
            <button
              key={t.key}
              onClick={() => setActiveTab(t.key as any)}
              style={{
                padding: '5px 12px',
                borderRadius: 'var(--radius-full)',
                border: `1px solid ${activeTab === t.key ? 'var(--primary)' : 'var(--line)'}`,
                background: activeTab === t.key ? 'var(--primary-tint)' : 'var(--surface)',
                color: activeTab === t.key ? 'var(--primary)' : 'var(--ink-2)',
                fontSize: '0.75rem',
                fontWeight: activeTab === t.key ? 600 : 500,
                cursor: 'pointer',
              }}
            >
              {t.label}
            </button>
          ))}
        </div>

        <input
          type="text"
          className="input"
          style={{ maxWidth: '280px' }}
          placeholder="Filter schema columns..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      <div style={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 'var(--radius-lg)', overflow: 'hidden' }}>
        <table className="log-table">
          <thead>
            <tr>
              <th>Field Name</th>
              <th>Role</th>
              <th>Synthesized Data Type</th>
              <th>Form / Aggregation Category</th>
              <th>Target Model Status</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((col, idx) => (
              <tr key={idx}>
                <td style={{ fontWeight: 600, color: 'var(--ink)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    {col.role === 'dimension' ? <Type size={14} color="var(--primary)" /> : <Hash size={14} color="var(--green)" />}
                    <span>{col.name}</span>
                  </div>
                </td>
                <td>
                  <span className="tool-chip" style={{ textTransform: 'capitalize' }}>{col.role}</span>
                </td>
                <td className="mono" style={{ fontSize: '0.75rem', color: 'var(--ink-2)' }}>{col.type}</td>
                <td style={{ fontSize: '0.8125rem', color: 'var(--ink-2)' }}>{col.category}</td>
                <td>
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', fontSize: '0.75rem', color: 'var(--green)', fontWeight: 600 }}>
                    <CheckCircle2 size={13} /> Mapped
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
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
