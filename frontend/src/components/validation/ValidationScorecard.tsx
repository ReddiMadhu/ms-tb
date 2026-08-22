import React from 'react';
import { ShieldCheck, CheckCircle2, AlertTriangle, XCircle, Info } from 'lucide-react';

export interface GateStatus {
  name: string;
  score: number | null | undefined;
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

function buildGate(
  name: string,
  score: number | null | undefined,
  threshold: number,
  description: string,
  extraCondition: boolean = true
): GateStatus {
  const isEvaluated = score !== null && score !== undefined;
  const passed = isEvaluated ? (score >= threshold && extraCondition) : false;
  // ONLY trigger gate failure and blockers when score is explicitly evaluated and below threshold
  const blockers = isEvaluated && (!passed) ? 1 : 0;

  return {
    name,
    score,
    threshold,
    passed,
    blockers,
    description,
  };
}

export const ValidationScorecard: React.FC<ValidationScorecardProps> = ({
  gates: customGates,
  autoPublishEligible,
  totalBlockers = 0,
  job,
}) => {
  // Compute gates from actual DB job record if provided (preserving null/undefined for pending evaluations)
  const computedGates: GateStatus[] = [
    buildGate(
      'Structural Gate',
      job?.structural_confidence,
      0.99,
      'Schema tables, column mappings, and relationship models'
    ),
    buildGate(
      'Financial & KPI Numeric Gate',
      job?.financial_kpi_confidence,
      0.98,
      'Direct SQL & JSON API aggregation parity against source warehouse'
    ),
    buildGate(
      'Security & RLS Gate',
      job?.security_confidence,
      1.0,
      'Security filter translation and USERNAME() delimiter isolation',
      job?.security_parity !== false
    ),
    buildGate(
      'Visual & Layout Gate',
      job?.visual_confidence,
      0.80,
      'Worksheet visual types, legends, filters, and container layouts'
    ),
  ];

  const gates = customGates || computedGates;
  const evaluatedGates = gates.filter((g) => g.score !== null && g.score !== undefined);
  const allEvaluated = gates.length > 0 && evaluatedGates.length === gates.length;
  const allPassed = allEvaluated && gates.every((g) => g.passed);
  const totalGateBlockers = gates.reduce((sum, g) => sum + g.blockers, 0);

  const isAutoPublishApproved =
    autoPublishEligible !== undefined
      ? autoPublishEligible
      : (allPassed && totalBlockers === 0 && totalGateBlockers === 0);

  const hasExplicitBlockers = (totalBlockers > 0) || (totalGateBlockers > 0);

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
            background: isAutoPublishApproved
              ? 'var(--green-tint)'
              : hasExplicitBlockers
              ? 'var(--red-tint, rgba(239, 68, 68, 0.1))'
              : 'var(--yellow-tint)',
            color: isAutoPublishApproved
              ? 'var(--green)'
              : hasExplicitBlockers
              ? 'var(--red, #ef4444)'
              : 'var(--yellow)',
            fontSize: '0.8125rem',
            fontWeight: 700,
          }}
        >
          {isAutoPublishApproved ? (
            <CheckCircle2 size={16} />
          ) : hasExplicitBlockers ? (
            <XCircle size={16} />
          ) : (
            <AlertTriangle size={16} />
          )}
          <span>
            {isAutoPublishApproved
              ? 'Auto-Publish Approved'
              : hasExplicitBlockers
              ? `${(totalBlockers || totalGateBlockers)} Blocker${(totalBlockers || totalGateBlockers) > 1 ? 's' : ''} Detected`
              : 'Quality Gate Review Pending'}
          </span>
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
          const isEvaluated = gate.score !== null && gate.score !== undefined;
          const percent = isEvaluated ? (gate.score! * 100).toFixed(1) : null;
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
                {!isEvaluated ? (
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', fontSize: '0.6875rem', fontWeight: 600, color: 'var(--ink-3)' }}>
                    <Info size={14} /> Pending
                  </span>
                ) : gate.passed ? (
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
                  color: !isEvaluated ? 'var(--ink-3)' : gate.passed ? 'var(--green)' : 'var(--red)',
                  marginBottom: '4px',
                }}
              >
                {isEvaluated ? `${percent}%` : 'Pending'}
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
