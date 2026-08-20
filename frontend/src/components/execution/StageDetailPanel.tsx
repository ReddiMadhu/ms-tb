import React from 'react';
import { Link } from 'react-router-dom';
import {
  Search,
  GitBranch,
  Layers,
  Copy,
  Code,
  Sparkles,
  LayoutDashboard,
  Database,
  FileOutput,
  FileSpreadsheet,
  ShieldCheck,
  FileText,
  ExternalLink,
  Clock,
  CheckCircle2,
} from 'lucide-react';
import { getStageConfig } from '../../config/pipeline.config';
import { StatusBadge } from '../ui/StatusBadge';

interface StageDetailPanelProps {
  stageId: string;
  jobId: string;
  status?: string;
  durationSeconds?: number;
  stats?: Record<string, string | number>;
  logs?: string[];
  artifacts?: { name: string; path: string; size?: string }[];
}

const ICON_MAP: Record<string, React.ComponentType<{ size?: number }>> = {
  Search,
  GitBranch,
  Layers,
  Copy,
  Code,
  Sparkles,
  LayoutDashboard,
  Database,
  FileOutput,
  FileSpreadsheet,
  ShieldCheck,
  FileText,
};

export const StageDetailPanel: React.FC<StageDetailPanelProps> = ({
  stageId,
  jobId,
  status = 'COMPLETED',
  durationSeconds,
  stats,
  logs = [],
  artifacts = [],
}) => {
  const stage = getStageConfig(stageId);
  if (!stage) return null;

  const IconComponent = ICON_MAP[stage.icon] || Code;

  // Custom action link per stage
  const getStageAction = () => {
    switch (stageId) {
      case 'DISCOVERY':
      case 'METRIC_DEDUPLICATION':
        return { label: 'Explore Object Catalog', to: `/jobs/${jobId}/objects` };
      case 'GRAPH':
        return { label: 'View Lineage Explorer', to: `/jobs/${jobId}/lineage` };
      case 'SEMANTIC':
      case 'IR_COMPILE':
      case 'AI_TRANSLATE':
        return { label: 'Inspect Calculation Logic Conversion', to: `/jobs/${jobId}/logic` };
      case 'VIZ':
      case 'WORKBOOK_EMIT_STAGING':
        return { label: 'View Visual Conversion Report', to: `/jobs/${jobId}/dashboards` };
      case 'STATIC_VALIDATE':
      case 'REPORT':
      case 'DATASOURCE_EMIT':
      case 'HYPER_BUILD':
        return { label: 'View Publish & Export Center', to: `/jobs/${jobId}/exports` };
      default:
        return null;
    }
  };

  const action = getStageAction();

  return (
    <div className="stage-detail-panel">
      <div className="stage-detail-header">
        <div className="stage-detail-title-group">
          <div className="stage-detail-icon-wrap">
            <IconComponent size={24} />
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <h3
                style={{
                  fontSize: '1.125rem',
                  fontWeight: 600,
                  color: 'var(--ink)',
                  margin: 0,
                }}
              >
                Stage {stage.number}: {stage.title}
              </h3>
              <StatusBadge status={status} type="stage" size="sm" />
            </div>
            <p
              style={{
                fontSize: '0.8125rem',
                color: 'var(--ink-2)',
                margin: '3px 0 0 0',
              }}
            >
              {stage.description}
            </p>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {durationSeconds !== undefined && (
            <div
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '5px',
                fontSize: '0.8125rem',
                color: 'var(--ink-3)',
                fontFamily: 'var(--font-mono)',
              }}
            >
              <Clock size={14} />
              <span>{durationSeconds}s</span>
            </div>
          )}
          {action && (
            <Link
              to={action.to}
              className="btn btn-secondary"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                padding: '6px 12px',
                fontSize: '0.8125rem',
                fontWeight: 600,
              }}
            >
              <span>{action.label}</span>
              <ExternalLink size={13} />
            </Link>
          )}
        </div>
      </div>

      {/* Stats row if available */}
      {stats && Object.keys(stats).length > 0 && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
            gap: '12px',
            marginBottom: '20px',
          }}
        >
          {Object.entries(stats).map(([k, v]) => (
            <div
              key={k}
              style={{
                padding: '12px 14px',
                background: 'var(--field)',
                borderRadius: 'var(--radius-md)',
                border: '1px solid var(--line)',
              }}
            >
              <div
                style={{
                  fontSize: '0.6875rem',
                  textTransform: 'uppercase',
                  color: 'var(--ink-3)',
                  fontWeight: 600,
                  letterSpacing: '0.04em',
                }}
              >
                {k.replace(/_/g, ' ')}
              </div>
              <div
                style={{
                  fontSize: '1.25rem',
                  fontWeight: 700,
                  color: 'var(--ink)',
                  marginTop: '4px',
                }}
              >
                {v}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Artifacts if any */}
      {artifacts.length > 0 && (
        <div style={{ marginBottom: '20px' }}>
          <h4
            style={{
              fontSize: '0.8125rem',
              fontWeight: 600,
              color: 'var(--ink-2)',
              marginBottom: '8px',
              textTransform: 'uppercase',
              letterSpacing: '0.04em',
            }}
          >
            Generated Stage Artifacts
          </h4>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
            {artifacts.map((art) => (
              <span
                key={art.name}
                className="tool-chip"
                style={{ background: 'var(--surface)', padding: '5px 10px' }}
              >
                <CheckCircle2 size={13} color="var(--green)" />
                <span style={{ fontWeight: 600 }}>{art.name}</span>
                {art.size && <span style={{ color: 'var(--ink-3)' }}>({art.size})</span>}
              </span>
            ))}
          </div>
        </div>
      )}

    </div>
  );
};

export default StageDetailPanel;
