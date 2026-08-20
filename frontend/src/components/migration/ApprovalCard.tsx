import React, { useState } from 'react';
import { CheckCircle2, Sparkles, HelpCircle, Check } from 'lucide-react';

export interface ApprovalOption {
  id: string;
  title: string;
  expression: string;
  description: string;
  confidence: number;
  tradeoff: string;
}

interface ApprovalCardProps {
  taskId: string;
  objectName: string;
  sourceExpression: string;
  options: ApprovalOption[];
  onSelectOption: (taskId: string, optionId: string) => void;
}

export const ApprovalCard: React.FC<ApprovalCardProps> = ({
  taskId,
  objectName,
  sourceExpression,
  options,
  onSelectOption,
}) => {
  const [selectedOptionId, setSelectedOptionId] = useState<string>(options[0]?.id || '');

  return (
    <div
      style={{
        background: 'var(--surface)',
        border: '1px solid var(--line-strong)',
        borderRadius: 'var(--radius-lg)',
        padding: '20px',
        marginBottom: '16px',
        boxShadow: 'var(--shadow-card)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
        <HelpCircle size={18} color="var(--primary)" />
        <h4 style={{ fontSize: '0.9375rem', fontWeight: 600, color: 'var(--ink)', margin: 0 }}>
          Ambiguity Resolution Required: {objectName}
        </h4>
      </div>

      <p style={{ fontSize: '0.8125rem', color: 'var(--ink-2)', marginBottom: '14px' }}>
        The engine discovered multiple mathematically equivalent translation strategies. Select
        the desired behavior for target Tableau worksheets.
      </p>

      <div
        style={{
          padding: '10px 14px',
          background: 'var(--inset)',
          borderRadius: 'var(--radius-sm)',
          fontFamily: 'var(--font-mono)',
          fontSize: '0.8125rem',
          color: 'var(--ink)',
          marginBottom: '14px',
        }}
      >
        <span style={{ color: 'var(--ink-3)', marginRight: '8px' }}>Source MSTR:</span>
        {sourceExpression}
      </div>

      <div className="approval-card-options">
        {options.map((opt) => {
          const isSelected = selectedOptionId === opt.id;
          return (
            <div
              key={opt.id}
              className={`approval-option-box ${isSelected ? 'selected' : ''}`}
              onClick={() => setSelectedOptionId(opt.id)}
            >
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  marginBottom: '6px',
                }}
              >
                <span style={{ fontWeight: 600, fontSize: '0.875rem', color: 'var(--ink)' }}>
                  {opt.title}
                </span>
                <span
                  style={{
                    fontSize: '0.75rem',
                    fontWeight: 700,
                    color: opt.confidence >= 0.9 ? 'var(--green)' : 'var(--yellow)',
                  }}
                >
                  {Math.round(opt.confidence * 100)}% Match
                </span>
              </div>

              <div
                style={{
                  padding: '8px',
                  background: 'var(--surface)',
                  borderRadius: 'var(--radius-sm)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '0.75rem',
                  color: 'var(--ink)',
                  marginBottom: '8px',
                }}
              >
                {opt.expression}
              </div>

              <div style={{ fontSize: '0.75rem', color: 'var(--ink-2)', lineHeight: 1.4 }}>
                {opt.description}
              </div>

              <div
                style={{
                  fontSize: '0.6875rem',
                  color: 'var(--ink-3)',
                  marginTop: '6px',
                  fontStyle: 'italic',
                }}
              >
                Tradeoff: {opt.tradeoff}
              </div>
            </div>
          );
        })}
      </div>

      <div
        style={{
          display: 'flex',
          justifyContent: 'flex-end',
          marginTop: '16px',
          paddingTop: '12px',
          borderTop: '1px solid var(--line)',
        }}
      >
        <button
          onClick={() => onSelectOption(taskId, selectedOptionId)}
          className="btn btn-primary"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '6px',
            padding: '7px 16px',
            fontSize: '0.8125rem',
            fontWeight: 600,
          }}
        >
          <Check size={14} />
          <span>Apply Chosen Strategy</span>
        </button>
      </div>
    </div>
  );
};

export default ApprovalCard;
