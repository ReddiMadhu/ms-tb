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
  overallScore: number; // 0.0 to 1.0
  categories?: ConfidenceCategory[];
  showDrilldown?: boolean;
}

export const ConfidenceCard: React.FC<ConfidenceCardProps> = ({
  jobId,
  overallScore,
  categories = [
    {
      name: 'Structural Parity',
      score: 0.992,
      passed: true,
      description: 'Tables, fields, measures, hierarchies, joins matching ground truth',
    },
    {
      name: 'Numeric & Financial KPI',
      score: 1.0,
      passed: true,
      description: '100% value parity against MSTR JSON data API results',
    },
    {
      name: 'Security & Entitlements',
      score: 1.0,
      passed: true,
      description: 'Row-level security predicates and user filters verified',
    },
    {
      name: 'Visual & Layout Fidelity',
      score: 0.964,
      passed: true,
      description: 'Visual chart mappings, axes, color palettes, and container layout',
    },
  ],
  showDrilldown = true,
}) => {
  const percent = Math.round(overallScore * 100);

  const getScoreColor = (score: number) => {
    if (score >= 0.95) return 'var(--green)';
    if (score >= 0.85) return 'var(--yellow)';
    return 'var(--red)';
  };

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
              background: `color-mix(in srgb, ${getScoreColor(overallScore)} 12%, transparent)`,
              color: getScoreColor(overallScore),
            }}
          >
            <span>{percent}%</span>
            <span style={{ fontSize: '0.8125rem', fontWeight: 600 }}>
              {percent >= 95 ? 'High Confidence' : percent >= 80 ? 'Moderate' : 'Review Needed'}
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

      <div className="confidence-bars-grid">
        {categories.map((cat) => {
          const catPercent = Math.round(cat.score * 100);
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
                  {catPercent}%
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
    </div>
  );
};

export default ConfidenceCard;
