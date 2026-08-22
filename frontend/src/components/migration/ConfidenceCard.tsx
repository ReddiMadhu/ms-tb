import React from 'react';
import { ShieldCheck, Info, ChevronRight } from 'lucide-react';
import { Link } from 'react-router-dom';

interface ConfidenceCategory {
  name: string;
  score: number; // 0.0 to 1.0
  passed: boolean;
  description: string;
}

interface ConfidenceCardProps {
  jobId: string;
  overallScore?: number | null; // 0.0 to 1.0
  categories?: ConfidenceCategory[];
  job?: {
    structural_confidence?: number | null;
    financial_kpi_confidence?: number | null;
    security_confidence?: number | null;
    visual_confidence?: number | null;
    status?: string;
  } | null;
  showDrilldown?: boolean;
}

export const ConfidenceCard: React.FC<ConfidenceCardProps> = ({
  jobId,
  overallScore,
  categories: explicitCategories,
  job,
  showDrilldown = true,
}) => {
  // Derive categories from job if not explicitly provided
  const categories: ConfidenceCategory[] = explicitCategories || (job && (
    job.structural_confidence != null ||
    job.financial_kpi_confidence != null ||
    job.security_confidence != null ||
    job.visual_confidence != null
  ) ? [
    {
      name: 'Structural Parity',
      score: job.structural_confidence ?? 0,
      passed: (job.structural_confidence ?? 0) >= 0.99,
      description: 'Tables, fields, measures, hierarchies, joins matching ground truth',
    },
    {
      name: 'Numeric & Financial KPI',
      score: job.financial_kpi_confidence ?? 0,
      passed: (job.financial_kpi_confidence ?? 0) >= 0.98,
      description: 'Value parity against MSTR JSON data API results',
    },
    {
      name: 'Security & Entitlements',
      score: job.security_confidence ?? 0,
      passed: (job.security_confidence ?? 0) >= 1.0,
      description: 'Row-level security predicates and user filters verified',
    },
    {
      name: 'Visual & Layout Fidelity',
      score: job.visual_confidence ?? 0,
      passed: (job.visual_confidence ?? 0) >= 0.80,
      description: 'Visual chart mappings, axes, color palettes, and layout',
    },
  ] : []);

  const hasScore = typeof overallScore === 'number' && overallScore > 0;
  const percent = hasScore ? Math.round(overallScore * 100) : null;

  const getScoreColor = (score?: number | null) => {
    if (score == null || score === 0) return 'var(--ink-3)';
    if (score >= 0.95) return 'var(--green)';
    if (score >= 0.85) return 'var(--yellow)';
    return 'var(--red)';
  };

  const badgeColor = getScoreColor(overallScore);

  return (
    <div className="confidence-card">
      <div className="confidence-header">
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <ShieldCheck size={20} color="var(--primary)" />
            <h3
              style={{
                fontSize: '1.0625rem',
                fontWeight: 600,
                color: 'var(--ink)',
                margin: 0,
              }}
            >
              Migration Trust &amp; Confidence Score
            </h3>
          </div>
          <p
            style={{
              fontSize: '0.8125rem',
              color: 'var(--ink-2)',
              margin: '4px 0 0 0',
            }}
          >
            Multi-tier algorithmic validation score across data, formula, and visual parity
          </p>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          <div
            className="confidence-score-badge"
            style={{
              background: percent !== null ? `color-mix(in srgb, ${badgeColor} 12%, transparent)` : 'var(--field)',
              color: badgeColor,
            }}
          >
            <span>{percent !== null ? `${percent}%` : '—'}</span>
            <span style={{ fontSize: '0.8125rem', fontWeight: 600 }}>
              {percent === null
                ? 'Pending Evaluation'
                : percent >= 95
                ? 'High Confidence'
                : percent >= 80
                ? 'Moderate'
                : 'Review Needed'}
            </span>
          </div>

          {showDrilldown && (
            <Link
              to={`/jobs/${jobId}/validation`}
              className="btn btn-ghost"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
                padding: '6px 10px',
                fontSize: '0.8125rem',
                fontWeight: 600,
                color: 'var(--primary)',
              }}
            >
              <span>Inspect Matrix</span>
              <ChevronRight size={14} />
            </Link>
          )}
        </div>
      </div>

      {categories.length === 0 ? (
        <div
          style={{
            padding: '24px 16px',
            textAlign: 'center',
            background: 'var(--field)',
            borderRadius: 'var(--radius-md)',
            border: '1px dashed var(--line)',
            color: 'var(--ink-2)',
            fontSize: '0.8125rem',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '8px',
          }}
        >
          <Info size={16} color="var(--ink-3)" />
          <span>Multi-tier validation confidence scores will populate once quality gate evaluation runs.</span>
        </div>
      ) : (
        <div className="confidence-bars-grid">
          {categories.map((cat) => {
            const hasCatScore = typeof cat.score === 'number' && cat.score > 0;
            const catPercent = hasCatScore ? Math.round(cat.score * 100) : 0;
            const color = getScoreColor(cat.score);

            return (
              <div key={cat.name} className="confidence-bar-item">
                <div className="confidence-bar-label">
                  <span style={{ color: 'var(--ink)', fontWeight: 600 }}>{cat.name}</span>
                  <span
                    style={{
                      color,
                      fontWeight: 700,
                      fontFamily: 'var(--font-mono)',
                    }}
                  >
                    {hasCatScore ? `${catPercent}%` : 'Pending'}
                  </span>
                </div>
                <div className="confidence-progress-track">
                  <div
                    className="confidence-progress-fill"
                    style={{
                      width: `${catPercent}%`,
                      backgroundColor: color,
                    }}
                  />
                </div>
                <span
                  style={{
                    fontSize: '0.6875rem',
                    color: 'var(--ink-3)',
                    lineHeight: 1.3,
                    marginTop: '2px',
                  }}
                >
                  {cat.description}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default ConfidenceCard;
