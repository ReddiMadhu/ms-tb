import React, { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  History,
  ArrowLeft,
  Search,
  Download,
  Filter,
  ShieldCheck,
  Clock,
  Terminal,
  Activity,
} from 'lucide-react';
import { api, type AuditEvent } from '../api';

export default function AuditTrail() {
  const { jobId } = useParams<{ jobId: string }>();
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [search, setSearch] = useState('');
  const [eventTypeFilter, setEventTypeFilter] = useState('all');

  useEffect(() => {
    api.getAuditLog(jobId)
      .then((res) => {
        setEvents(res.events || []);
      })
      .catch(() => setEvents([]));
  }, [jobId]);

  const filtered = events.filter((e) => {
    const detailsStr = JSON.stringify(e.details);
    const matchesSearch =
      e.event_type.toLowerCase().includes(search.toLowerCase()) ||
      detailsStr.toLowerCase().includes(search.toLowerCase());

    const matchesType = eventTypeFilter === 'all' || e.event_type === eventTypeFilter;

    return matchesSearch && matchesType;
  });

  const handleExportJSON = () => {
    const jsonStr = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(events, null, 2));
    const dlAnchor = document.createElement('a');
    dlAnchor.setAttribute('href', jsonStr);
    dlAnchor.setAttribute('download', `migration_audit_trail_${jobId || 'job'}.json`);
    dlAnchor.click();
  };

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
                fontSize: '1.5rem',
                fontWeight: 700,
                color: 'var(--ink)',
                letterSpacing: '-0.02em',
                margin: 0,
              }}
            >
              Audit Trail &amp; Telemetry Log ({events.length} Events)
            </h1>
          </div>

          <button
            onClick={handleExportJSON}
            className="btn btn-secondary"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              padding: '8px 14px',
              fontSize: '0.8125rem',
            }}
          >
            <Download size={14} />
            <span>Export Audit JSON</span>
          </button>
        </div>
      </div>

      {/* ── Search & Event Filters ───────────────────────────────── */}
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
            { key: 'all', label: `All Events (${events.length})` },
            { key: 'mstr_api_call', label: 'API Calls' },
            { key: 'object_extracted', label: 'Object Extractions' },
            { key: 'object_compiled', label: 'IR Compilations' },
            { key: 'validation_check', label: 'Validation Sweeps' },
            { key: 'publish_action', label: 'Publish Actions' },
          ].map((f) => (
            <button
              key={f.key}
              onClick={() => setEventTypeFilter(f.key)}
              style={{
                padding: '6px 14px',
                borderRadius: 'var(--radius-full)',
                border: '1px solid',
                borderColor: eventTypeFilter === f.key ? 'var(--primary)' : 'var(--line)',
                background: eventTypeFilter === f.key ? 'var(--primary-tint)' : 'var(--surface)',
                color: eventTypeFilter === f.key ? 'var(--primary)' : 'var(--ink-2)',
                fontSize: '0.8125rem',
                fontWeight: eventTypeFilter === f.key ? 600 : 500,
                cursor: 'pointer',
              }}
            >
              {f.label}
            </button>
          ))}
        </div>

        <div className="search-bar" style={{ minWidth: '320px' }}>
          <Search size={16} className="search-icon" />
          <input
            type="text"
            className="input"
            placeholder="Search audit trail by keyword or payload..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      {/* ── Event Log Table ──────────────────────────────────────── */}
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
              <th>Timestamp</th>
              <th>Event Type</th>
              <th>Event Payload Details</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((e) => (
              <tr key={e.id}>
                <td
                  className="mono"
                  style={{
                    fontSize: '0.75rem',
                    color: 'var(--ink-3)',
                    whiteSpace: 'nowrap',
                    width: '180px',
                  }}
                >
                  {e.timestamp}
                </td>
                <td style={{ width: '180px' }}>
                  <span className="tool-chip" style={{ textTransform: 'capitalize' }}>
                    {e.event_type.replace(/_/g, ' ')}
                  </span>
                </td>
                <td>
                  <pre
                    style={{
                      margin: 0,
                      fontFamily: 'var(--font-mono)',
                      fontSize: '0.75rem',
                      color: 'var(--ink)',
                      background: 'var(--inset)',
                      padding: '8px 12px',
                      borderRadius: 'var(--radius-sm)',
                      overflowX: 'auto',
                    }}
                  >
                    {JSON.stringify(e.details, null, 2)}
                  </pre>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
