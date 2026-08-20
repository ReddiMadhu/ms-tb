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
  job?: {
    structural_confidence?: number | null;
    financial_kpi_confidence?: number | null;
    security_confidence?: number | null;
    visual_confidence?: number | null;
    security_parity?: boolean | null;
    status?: string;
  } | null;
}

export const ValidationScorecard: React.FC<ValidationScorecardProps> = ({
  gates: customGates,
  autoPublishEligible,
  totalBlockers = 0,
  job,
}) => {
  // Compute gates from actual DB job record if provided
  const structuralScore = job?.structural_confidence ?? 1.0;
  const financialScore = job?.financial_kpi_confidence ?? 0.0;
  const securityScore = job?.security_confidence ?? 1.0;
  const visualScore = job?.visual_confidence ?? 1.0;

  const computedGates: GateStatus[] = [
    {
      name: 'Structural Gate',
      score: structuralScore,
      threshold: 0.99,
      passed: structuralScore >= 0.99,
      blockers: structuralScore < 0.99 ? 1 : 0,
      description: 'Schema tables, column mappings, and relationship models',
    },
    {
      name: 'Financial & KPI Numeric Gate',
      score: financialScore,
      threshold: 0.98,
      passed: financialScore >= 0.98,
      blockers: financialScore < 0.98 ? 1 : 0,
      description: 'Direct SQL & JSON API aggregation parity against source warehouse',
    },
    {
      name: 'Security & RLS Gate',
      score: securityScore,
      threshold: 1.0,
      passed: securityScore >= 1.0 && (job?.security_parity !== false),
      blockers: securityScore < 1.0 ? 1 : 0,
      description: 'Security filter translation and USERNAME() delimiter isolation',
    },
    {
      name: 'Visual & Layout Gate',
      score: visualScore,
      threshold: 0.80,
      passed: visualScore >= 0.80,
      blockers: visualScore < 0.80 ? 1 : 0,
      description: 'Worksheet visual types, legends, filters, and container layouts',
    },
  ];

  const gates = customGates || computedGates;
  const allPassed = gates.every(g => g.passed);
  const isAutoPublishApproved = autoPublishEligible !== undefined ? autoPublishEligible : (allPassed && totalBlockers === 0);
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
            background: isAutoPublishApproved ? 'var(--green-tint)' : 'var(--yellow-tint)',
            color: isAutoPublishApproved ? 'var(--green)' : 'var(--yellow)',
            fontSize: '0.8125rem',
            fontWeight: 700,
          }}
        >
          {isAutoPublishApproved ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
          <span>{isAutoPublishApproved ? 'Auto-Publish Approved' : `${totalBlockers > 0 ? totalBlockers : 'Quality'} Gate Review Pending`}</span>
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
