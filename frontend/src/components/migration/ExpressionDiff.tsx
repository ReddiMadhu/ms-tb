import React, { useState } from 'react';
import { Copy, Check, Code, Sparkles } from 'lucide-react';

interface ExpressionDiffProps {
  sourceExpression: string;
  targetExpression: string;
  sourceLabel?: string;
  targetLabel?: string;
  method?: string;
  confidence?: number;
  explanation?: string;
}

export const ExpressionDiff: React.FC<ExpressionDiffProps> = ({
  sourceExpression,
  targetExpression,
  sourceLabel = 'MicroStrategy Expression',
  targetLabel = 'Tableau Calculated Field',
  method = 'Rule Compiler',
  confidence,
  explanation,
}) => {
  const [copiedTarget, setCopiedTarget] = useState(false);

  const handleCopyTarget = () => {
    navigator.clipboard.writeText(targetExpression);
    setCopiedTarget(true);
    setTimeout(() => setCopiedTarget(false), 2000);
  };

  return (
    <div style={{ margin: '16px 0' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: '8px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span className="tool-chip">
            <Sparkles size={12} color="var(--primary)" />
            <span>Method: {method}</span>
          </span>
          <span
            className="tool-chip"
            style={{
              color:
                confidence != null
                  ? confidence >= 0.9
                    ? 'var(--green)'
                    : confidence >= 0.8
                    ? 'var(--yellow)'
                    : 'var(--red)'
                  : 'var(--ink-2)',
            }}
          >
            {confidence != null
              ? `Confidence: ${Math.round(confidence * 100)}%`
              : 'Confidence: Pending / Rule-based'}
          </span>
        </div>

        <button
          onClick={handleCopyTarget}
          className="btn btn-ghost"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '5px',
            padding: '4px 8px',
            fontSize: '0.75rem',
          }}
        >
          {copiedTarget ? (
            <>
              <Check size={13} color="var(--green)" />
              <span style={{ color: 'var(--green)' }}>Copied Target</span>
            </>
          ) : (
            <>
              <Copy size={13} />
              <span>Copy Tableau Calc</span>
            </>
          )}
        </button>
      </div>

      <div className="expression-diff-viewer">
        <div className="diff-pane">
          <div className="diff-pane-header">
            <span>{sourceLabel}</span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.6875rem' }}>
              MSTR AST
            </span>
          </div>
          <div className="diff-pane-code">{sourceExpression}</div>
        </div>

        <div className="diff-pane" style={{ borderColor: 'var(--line-strong)' }}>
          <div
            className="diff-pane-header"
            style={{ background: 'var(--primary-tint)' }}
          >
            <span style={{ color: 'var(--primary)', fontWeight: 700 }}>
              {targetLabel}
            </span>
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '0.6875rem',
                color: 'var(--primary)',
              }}
            >
              Tableau Dialect
            </span>
          </div>
          <div
            className="diff-pane-code"
            style={{ color: 'var(--ink)', background: 'var(--surface)' }}
          >
            {targetExpression}
          </div>
        </div>
      </div>

      {explanation && (
        <div
          style={{
            padding: '10px 14px',
            background: 'var(--field)',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--line)',
            fontSize: '0.8125rem',
            color: 'var(--ink-2)',
            display: 'flex',
            alignItems: 'flex-start',
            gap: '8px',
          }}
        >
          <Sparkles size={14} color="var(--primary)" style={{ marginTop: '2px', flexShrink: 0 }} />
          <div>
            <strong style={{ color: 'var(--ink)', marginRight: '6px' }}>
              Translation Note:
            </strong>
            {explanation}
          </div>
        </div>
      )}
    </div>
  );
};

export default ExpressionDiff;
