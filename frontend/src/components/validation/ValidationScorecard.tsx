import React from 'react';
import { ShieldCheck, CheckCircle2, AlertTriangle, XCircle, Info } from 'lucide-react';

export interface GateStatus {
  name: string;
  score: number;
  threshold: number;
  passed: boolean;
  blockers: number;
  description: string;
}

interface ValidationScorecardProps {
  gates?: GateStatus[];
  autoPublishEligible?: boolean;
  totalBlockers?: number;
}

const DEFAULT_GATES: GateStatus[] = [
  {
    name: 'Structural Gate',
    score: 0.992,
    threshold: 0.98,
    passed: true,
    blockers: 0,
    description: 'Schema tables, column mappings, and relationship models',
  },
  {
    name: 'Financial & KPI Numeric Gate',
    score: 0.995,
    threshold: 0.98,
    passed: true,
    blockers: 0,
    description: 'Direct SQL & JSON API aggregation parity against source warehouse',
  },
  {
    name: 'Security & RLS Gate',
    score: 1.0,
    threshold: 1.0,
    passed: true,
    blockers: 0,
    description: 'Security filter translation and USERNAME() delimiter isolation',
  },
  {
    name: 'Visual & Layout Gate',
    score: 0.91,
    threshold: 0.85,
    passed: true,
    blockers: 0,
    description: 'Worksheet visual types, legends, filters, and container layouts',
  },
];

export const ValidationScorecard: React.FC<ValidationScorecardProps> = ({
  gates = DEFAULT_GATES,
  autoPublishEligible = true,
  totalBlockers = 0,
}) => {
  return (
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
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: '20px',
        }}
      >
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <ShieldCheck size={20} color="var(--primary)" />
            <h3 style={{ fontSize: '1.0625rem', fontWeight: 600, color: 'var(--ink)', margin: 0 }}>
              4-Tier Promotion Gate Scorecard
            </h3>
          </div>
          <p style={{ fontSize: '0.8125rem', color: 'var(--ink-2)', margin: '4px 0 0 0' }}>
            Strict quality criteria gating automatic promotion from Staging to Production
          </p>
        </div>

        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            padding: '6px 14px',
            borderRadius: 'var(--radius-full)',
            background: autoPublishEligible ? 'var(--green-tint)' : 'var(--yellow-tint)',
            color: autoPublishEligible ? 'var(--green)' : 'var(--yellow)',
            fontSize: '0.8125rem',
            fontWeight: 700,
          }}
        >
          {autoPublishEligible ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
          <span>{autoPublishEligible ? 'Auto-Publish Approved' : `${totalBlockers} Blockers Pending`}</span>
        </div>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
          gap: '16px',
        }}
      >
        {gates.map((gate) => {
          const percent = (gate.score * 100).toFixed(1);
          const thresholdPercent = (gate.threshold * 100).toFixed(0);

          return (
            <div
              key={gate.name}
              style={{
                padding: '16px',
                background: 'var(--field)',
                borderRadius: 'var(--radius-md)',
                border: '1px solid var(--line)',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  marginBottom: '10px',
                }}
              >
                <span style={{ fontSize: '0.8125rem', fontWeight: 600, color: 'var(--ink)' }}>
                  {gate.name}
                </span>
                {gate.passed ? (
                  <CheckCircle2 size={16} color="var(--green)" />
                ) : (
                  <XCircle size={16} color="var(--red)" />
                )}
              </div>

              <div
                style={{
                  fontSize: '1.5rem',
                  fontWeight: 700,
                  fontFamily: 'var(--font-mono)',
                  color: gate.passed ? 'var(--green)' : 'var(--red)',
                  marginBottom: '4px',
                }}
              >
                {percent}%
              </div>

              <div style={{ fontSize: '0.6875rem', color: 'var(--ink-3)', marginBottom: '8px' }}>
                Required Threshold: &gt;={thresholdPercent}%
              </div>

              <div style={{ fontSize: '0.6875rem', color: 'var(--ink-2)', lineHeight: 1.3 }}>
                {gate.description}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default ValidationScorecard;
