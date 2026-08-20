import React, { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  Layers,
  ArrowLeft,
  Database,
  Table,
  GitBranch,
  Key,
  Hash,
  Type,
  ChevronRight,
} from 'lucide-react';
import { api } from '../api';
import { EmptyState } from '../components/ui/EmptyState';

interface TableEntity {
  id: string;
  name: string;
  rowCount: string;
  columnCount: number;
  columns: Array<{ name: string; type: string; isKey?: boolean; role: 'dimension' | 'measure' }>;
  joins: Array<{ targetTable: string; sourceKey: string; targetKey: string; cardinality: string }>;
}

export default function SemanticModel() {
  const { jobId } = useParams<{ jobId: string }>();
  const [tables, setTables] = useState<TableEntity[]>([]);
  const [selectedTableId, setSelectedTableId] = useState<string>('');

  useEffect(() => {
    if (!jobId) return;
    api.listObjects(jobId)
      .then((res) => {
        const objs = res.objects || [];
        const cubes = objs.filter((o) => o.type_name === 'cube' || o.type_name === 'dossier');
        const attributes = objs.filter((o) => o.type_name === 'attribute');
        const metrics = objs.filter((o) => o.type_name === 'metric');

        const entities: TableEntity[] = [];

        if (cubes.length > 0) {
          cubes.forEach((c, idx) => {
            const mstrDef = c.mstr_definition as any;
            const cubeAttrs = mstrDef?.attributes || attributes;
            const cubeMetrics = mstrDef?.metrics || metrics;

            entities.push({
              id: c.id || `t-cube-${idx}`,
              name: c.name,
              rowCount: `${cubeAttrs.length} Attributes & ${cubeMetrics.length} Metrics`,
              columnCount: cubeAttrs.length + cubeMetrics.length,
              columns: [
                ...cubeAttrs.map((a: any) => ({
                  name: a.name || a,
                  type: a.data_type || (a.name?.toLowerCase().includes('date') ? 'DATE' : a.name?.toLowerCase().includes('id') ? 'INTEGER' : 'VARCHAR'),
                  isKey: Boolean(a.is_key || a.name?.toLowerCase().includes('id')),
                  role: 'dimension' as const,
                })),
                ...cubeMetrics.map((m: any) => ({
                  name: m.name || m,
                  type: m.data_type || 'NUMERIC',
                  role: 'measure' as const,
                })),
              ],
              joins: [],
            });
          });
        } else if (objs.length > 0) {
          entities.push({
            id: 't-model',
            name: 'Discovered Semantic Schema',
            rowCount: `${objs.length} Total Objects`,
            columnCount: objs.length,
            columns: objs.map((o) => ({
              name: o.name,
              type: o.type_name === 'metric' ? 'NUMERIC' : (o.name.toLowerCase().includes('date') ? 'DATE' : 'VARCHAR'),
              isKey: o.type_name === 'attribute' && o.name.toLowerCase().includes('id'),
              role: o.type_name === 'metric' ? 'measure' : 'dimension',
            })),
            joins: [],
          });
        }

        setTables(entities);
        if (entities.length > 0) {
          setSelectedTableId(entities[0].id);
        }
      })
      .catch(() => setTables([]));
  }, [jobId]);

  const selectedTable = tables.find((t) => t.id === selectedTableId) || tables[0] || null;

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
              Semantic Data Model ({tables.length} {tables.length === 1 ? 'Model' : 'Models'})
            </h2>
          </div>
        </div>
      </div>

      {/* ── Split Layout: Tables List vs Table Schema Inspector ─── */}
      {!selectedTable ? (
        <EmptyState
          icon={Layers}
          title="No Semantic Data Models Found"
          description="Connect your MicroStrategy project and run dossier discovery to inspect synthesized semantic tables and relationships."
        />
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: '320px 1fr', gap: '20px' }}>
        {/* Table Selector Sidebar */}
        <div
          style={{
            background: 'var(--surface)',
            border: '1px solid var(--line)',
            borderRadius: 'var(--radius-lg)',
            padding: '16px',
            height: 'fit-content',
            boxShadow: 'var(--shadow-card)',
          }}
        >
          <h3
            style={{
              fontSize: '0.8125rem',
              fontWeight: 600,
              color: 'var(--ink-2)',
              textTransform: 'uppercase',
              letterSpacing: '0.04em',
              marginBottom: '12px',
            }}
          >
            Model Entities ({tables.length} Tables)
          </h3>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {tables.map((t) => {
              const isSelected = selectedTableId === t.id;
              return (
                <div
                  key={t.id}
                  onClick={() => setSelectedTableId(t.id)}
                  style={{
                    padding: '10px 12px',
                    borderRadius: 'var(--radius-md)',
                    border: '1px solid',
                    borderColor: isSelected ? 'var(--primary)' : 'var(--line)',
                    background: isSelected ? 'var(--primary-tint)' : 'var(--field)',
                    cursor: 'pointer',
                    transition: 'all 0.15s ease',
                  }}
                >
                  <div
                    style={{
                      fontWeight: 600,
                      fontSize: '0.875rem',
                      color: isSelected ? 'var(--primary)' : 'var(--ink)',
                    }}
                  >
                    {t.name}
                  </div>
                  <div
                    style={{
                      fontSize: '0.6875rem',
                      color: 'var(--ink-3)',
                      marginTop: '3px',
                      display: 'flex',
                      gap: '8px',
                    }}
                  >
                    <span>{t.columnCount} columns</span>
                    <span>&bull;</span>
                    <span>{t.rowCount}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Selected Table Detail */}
        <div
          style={{
            background: 'var(--surface)',
            border: '1px solid var(--line)',
            borderRadius: 'var(--radius-lg)',
            padding: '24px',
            boxShadow: 'var(--shadow-card)',
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              paddingBottom: '16px',
              borderBottom: '1px solid var(--line)',
              marginBottom: '20px',
            }}
          >
            <div>
              <h2 style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--ink)', margin: 0 }}>
                {selectedTable.name}
              </h2>
              <span style={{ fontSize: '0.75rem', color: 'var(--ink-3)' }}>
                {selectedTable.rowCount} &bull; {selectedTable.columnCount} attributes &amp; metrics
              </span>
            </div>

            <span className="tool-chip">Logical Tableau Relation Table</span>
          </div>

          {/* Relationship Joins if any */}
          {selectedTable.joins.length > 0 && (
            <div style={{ marginBottom: '24px' }}>
              <h4
                style={{
                  fontSize: '0.8125rem',
                  fontWeight: 600,
                  color: 'var(--ink-2)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.04em',
                  marginBottom: '10px',
                }}
              >
                Relationship Integrity Joins
              </h4>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {selectedTable.joins.map((j, i) => (
                  <div
                    key={i}
                    style={{
                      padding: '10px 14px',
                      background: 'var(--field)',
                      borderRadius: 'var(--radius-sm)',
                      border: '1px solid var(--line)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      fontSize: '0.8125rem',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <GitBranch size={14} color="var(--primary)" />
                      <span>
                        Join to <strong style={{ color: 'var(--ink)' }}>{j.targetTable}</strong> on{' '}
                        <code className="mono">{j.sourceKey} = {j.targetKey}</code>
                      </span>
                    </div>
                    <span className="tool-chip" style={{ fontWeight: 700 }}>
                      {j.cardinality}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Columns Table */}
          <h4
            style={{
              fontSize: '0.8125rem',
              fontWeight: 600,
              color: 'var(--ink-2)',
              textTransform: 'uppercase',
              letterSpacing: '0.04em',
              marginBottom: '10px',
            }}
          >
            Attributes, Dimensions &amp; Measures
          </h4>
          <table className="log-table">
            <thead>
              <tr>
                <th>Field Name</th>
                <th>Data Role</th>
                <th>Data Type</th>
                <th>Key Constraint</th>
              </tr>
            </thead>
            <tbody>
              {selectedTable.columns.map((col, idx) => (
                <tr key={idx}>
                  <td style={{ fontWeight: 600, color: 'var(--ink)' }}>{col.name}</td>
                  <td>
                    <span
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '4px',
                        fontSize: '0.75rem',
                        fontWeight: 600,
                        color: col.role === 'measure' ? 'var(--green)' : 'var(--blue)',
                      }}
                    >
                      {col.role === 'measure' ? <Hash size={13} /> : <Type size={13} />}
                      <span style={{ textTransform: 'capitalize' }}>{col.role}</span>
                    </span>
                  </td>
                  <td className="mono" style={{ fontSize: '0.75rem', color: 'var(--ink-2)' }}>
                    {col.type}
                  </td>
                  <td>
                    {col.isKey ? (
                      <span
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '4px',
                          color: 'var(--primary)',
                          fontSize: '0.75rem',
                          fontWeight: 600,
                        }}
                      >
                        <Key size={12} />
                        <span>Primary/Foreign Key</span>
                      </span>
                    ) : (
                      <span style={{ color: 'var(--ink-3)', fontSize: '0.75rem' }}>—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      )}
    </div>
  );
}
