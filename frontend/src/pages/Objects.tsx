import React, { useEffect, useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import {
  Layers,
  ArrowLeft,
  Search,
  Filter,
  CheckCircle2,
  AlertTriangle,
  ArrowRight,
  Code,
  FileSpreadsheet,
  Database,
} from 'lucide-react';
import { api, type MigrationObject } from '../api';
import { StatusBadge } from '../components/ui/StatusBadge';
import { KpiCard } from '../components/ui/KpiCard';
import { EmptyState } from '../components/ui/EmptyState';

export default function Objects() {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const [objects, setObjects] = useState<MigrationObject[]>([]);
  const [typeFilter, setTypeFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!jobId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    api.listObjects(jobId)
      .then((res) => {
        setObjects(res.objects || []);
        setLoading(false);
      })
      .catch(() => {
        setObjects([]);
        setLoading(false);
      });
  }, [jobId]);

  const filteredObjects = objects.filter((o) => {
    const matchesSearch =
      o.name.toLowerCase().includes(search.toLowerCase()) ||
      o.mstr_id.toLowerCase().includes(search.toLowerCase()) ||
      (o.mstr_path && o.mstr_path.toLowerCase().includes(search.toLowerCase()));

    const matchesType = typeFilter === 'all' || o.type_name.toLowerCase() === typeFilter.toLowerCase();

    return matchesSearch && matchesType;
  });

  const countByType = (t: string) => objects.filter((o) => o.type_name === t).length;

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
              Extracted Catalog ({objects.length} Objects)
            </h2>
          </div>
        </div>
      </div>

      {/* ── Category Filters & Search ────────────────────────────── */}
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
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
          {[
            { key: 'all', label: `All (${objects.length})` },
            { key: 'metric', label: `Metrics (${countByType('metric')})` },
            { key: 'attribute', label: `Attributes (${countByType('attribute')})` },
            { key: 'dossier', label: `Dossiers (${countByType('dossier')})` },
            { key: 'cube', label: `Cubes (${countByType('cube')})` },
          ].map((t) => (
            <button
              key={t.key}
              onClick={() => setTypeFilter(t.key)}
              style={{
                padding: '6px 14px',
                borderRadius: 'var(--radius-full)',
                border: '1px solid',
                borderColor: typeFilter === t.key ? 'var(--primary)' : 'var(--line)',
                background: typeFilter === t.key ? 'var(--primary-tint)' : 'var(--surface)',
                color: typeFilter === t.key ? 'var(--primary)' : 'var(--ink-2)',
                fontSize: '0.8125rem',
                fontWeight: typeFilter === t.key ? 600 : 500,
                cursor: 'pointer',
              }}
            >
              {t.label}
            </button>
          ))}
        </div>

        <div className="search-bar" style={{ minWidth: '320px' }}>
          <Search size={16} className="search-icon" />
          <input
            type="text"
            className="input"
            placeholder="Search by object name, folder path, or ID..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      {/* ── Objects Table ────────────────────────────────────────── */}
      {filteredObjects.length === 0 ? (
        <EmptyState
          icon={Layers}
          title="No objects found"
          description="No objects match your active filter or search query."
          actionLabel="Clear Filters"
          onAction={() => {
            setTypeFilter('all');
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
                <th>Object Name</th>
                <th>Type</th>
                <th>MSTR Folder Path</th>
                <th>Conversion Status</th>
                <th>Parity Confidence</th>
                <th style={{ textAlign: 'right' }}>Inspection</th>
              </tr>
            </thead>
            <tbody>
              {filteredObjects.map((obj) => {
                const confPercent = Math.round((obj.confidence || 0.95) * 100);
                return (
                  <tr
                    key={obj.mstr_id}
                    style={{ cursor: 'pointer' }}
                    onClick={() => navigate(`/jobs/${jobId}/objects/${obj.mstr_id}`)}
                  >
                    <td>
                      <div style={{ fontWeight: 600, color: 'var(--ink)' }}>{obj.name}</div>
                      <div
                        style={{
                          fontSize: '0.6875rem',
                          color: 'var(--ink-3)',
                          fontFamily: 'var(--font-mono)',
                          marginTop: '2px',
                        }}
                      >
                        {obj.mstr_id}
                      </div>
                    </td>

                    <td>
                      <span className="tool-chip" style={{ textTransform: 'capitalize' }}>
                        {obj.type_name}
                      </span>
                    </td>

                    <td style={{ fontSize: '0.75rem', color: 'var(--ink-2)' }}>
                      {obj.mstr_path || '/Public Objects/'}
                    </td>

                    <td>
                      <StatusBadge status={obj.status} size="sm" />
                    </td>

                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span
                          style={{
                            fontFamily: 'var(--font-mono)',
                            fontSize: '0.8125rem',
                            fontWeight: 700,
                            color:
                              confPercent >= 95
                                ? 'var(--green)'
                                : confPercent >= 85
                                  ? 'var(--yellow)'
                                  : 'var(--red)',
                          }}
                        >
                          {confPercent}%
                        </span>
                        <div
                          style={{
                            width: '60px',
                            height: '4px',
                            background: 'var(--field)',
                            borderRadius: 'var(--radius-full)',
                            overflow: 'hidden',
                          }}
                        >
                          <div
                            style={{
                              height: '100%',
                              width: `${confPercent}%`,
                              background:
                                confPercent >= 95 ? 'var(--green)' : 'var(--yellow)',
                            }}
                          />
                        </div>
                      </div>
                    </td>

                    <td style={{ textAlign: 'right' }}>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          navigate(`/jobs/${jobId}/objects/${obj.mstr_id}`);
                        }}
                        className="btn btn-ghost"
                        style={{ padding: '6px' }}
                        title="Deep inspection"
                      >
                        <ArrowRight size={16} />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
