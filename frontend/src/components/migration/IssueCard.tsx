import React, { useState } from 'react';
import {
  AlertTriangle,
  OctagonX,
  Info,
  CheckCircle2,
  Edit3,
  GitPullRequest,
  Check,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { StatusBadge } from '../ui/StatusBadge';
import { ExpressionDiff } from './ExpressionDiff';

export interface IssueItem {
  id: string;
  job_id: string;
  object_id: string;
  object_name: string;
  object_type: string;
  severity: 'blocker' | 'warning' | 'info';
  reason: string;
  mstr_expression?: string;
  generated_calc?: string;
  confidence?: number;
  status: 'pending' | 'approved' | 'rejected' | 'redesign' | 'assigned';
  blast_radius?: string[];
  impact_description?: string;
  created_at?: string;
}

interface IssueCardProps {
  issue: IssueItem;
  onApprove?: (id: string) => void;
  onEdit?: (id: string, newCalc: string) => void;
  onRedesign?: (id: string) => void;
  isResolving?: boolean;
}

export const IssueCard: React.FC<IssueCardProps> = ({
  issue,
  onApprove,
  onEdit,
  onRedesign,
  isResolving = false,
}) => {
  const [expanded, setExpanded] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [editedCalc, setEditedCalc] = useState(issue.generated_calc || '');

  const hasExpressions = Boolean(issue.mstr_expression && issue.generated_calc);

  const handleSaveEdit = () => {
    onEdit?.(issue.id, editedCalc);
    setIsEditing(false);
  };

  return (
    <div className={`issue-card severity-${issue.severity}`}>
      <div className="issue-card-header">
        <div>
          <div className="issue-title">
            <span>{issue.object_name}</span>
            <span
              style={{
                fontSize: '0.75rem',
                fontWeight: 500,
                color: 'var(--ink-3)',
                textTransform: 'uppercase',
              }}
            >
              ({issue.object_type})
            </span>
            <StatusBadge status={issue.severity} type="severity" size="sm" />
            <StatusBadge status={issue.status} size="sm" />
          </div>
          <div
            style={{
              fontSize: '0.75rem',
              color: 'var(--ink-3)',
              marginTop: '2px',
              fontFamily: 'var(--font-mono)',
            }}
          >
            ID: {issue.object_id}
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {issue.status === 'pending' && onApprove && (
            <button
              onClick={() => onApprove(issue.id)}
              disabled={isResolving}
              className="btn btn-primary"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '5px',
                padding: '6px 12px',
                fontSize: '0.8125rem',
                fontWeight: 600,
              }}
            >
              <Check size={14} />
              <span>Approve Translation</span>
            </button>
          )}

          {hasExpressions && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="btn btn-ghost"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
                padding: '6px 10px',
                fontSize: '0.8125rem',
              }}
            >
              <span>{expanded ? 'Hide Details' : 'Inspect Formula'}</span>
              {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>
          )}
        </div>
      </div>

      <div className="issue-reason">{issue.reason}</div>

      {/* Blast Radius / Impact */}
      {issue.blast_radius && issue.blast_radius.length > 0 && (
        <div style={{ marginBottom: '12px' }}>
          <div
            style={{
              fontSize: '0.6875rem',
              textTransform: 'uppercase',
              fontWeight: 600,
              color: 'var(--ink-3)',
              letterSpacing: '0.04em',
              marginBottom: '6px',
            }}
          >
            Downstream Blast Radius ({issue.blast_radius.length} dependents)
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
            {issue.blast_radius.map((dep, idx) => (
              <span key={idx} className="blast-radius-tag">
                <GitPullRequest size={11} color="var(--primary)" />
                <span>{dep}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Expanded side-by-side diff */}
      {expanded && hasExpressions && (
        <div
          style={{
            marginTop: '14px',
            paddingTop: '14px',
            borderTop: '1px solid var(--line)',
          }}
        >
          {isEditing ? (
            <div style={{ marginBottom: '14px' }}>
              <label
                style={{
                  display: 'block',
                  fontSize: '0.8125rem',
                  fontWeight: 600,
                  color: 'var(--ink)',
                  marginBottom: '6px',
                }}
              >
                Edit Tableau Calculated Field
              </label>
              <textarea
                value={editedCalc}
                onChange={(e) => setEditedCalc(e.target.value)}
                style={{
                  width: '100%',
                  minHeight: '90px',
                  padding: '10px 12px',
                  borderRadius: 'var(--radius-sm)',
                  border: '1px solid var(--line-strong)',
                  background: 'var(--field)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '0.8125rem',
                  color: 'var(--ink)',
                  outline: 'none',
                }}
              />
              <div
                style={{
                  display: 'flex',
                  gap: '8px',
                  justifyContent: 'flex-end',
                  marginTop: '8px',
                }}
              >
                <button
                  onClick={() => setIsEditing(false)}
                  className="btn btn-secondary"
                  style={{ padding: '5px 12px', fontSize: '0.75rem' }}
                >
                  Cancel
                </button>
                <button
                  onClick={handleSaveEdit}
                  className="btn btn-primary"
                  style={{ padding: '5px 12px', fontSize: '0.75rem' }}
                >
                  Save &amp; Re-validate
                </button>
              </div>
            </div>
          ) : (
            <>
              <ExpressionDiff
                sourceExpression={issue.mstr_expression!}
                targetExpression={issue.generated_calc!}
                confidence={issue.confidence}
              />
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
                <button
                  onClick={() => setIsEditing(true)}
                  className="btn btn-secondary"
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '5px',
                    padding: '5px 10px',
                    fontSize: '0.75rem',
                  }}
                >
                  <Edit3 size={13} />
                  <span>Edit Calculated Field</span>
                </button>
                {onRedesign && (
                  <button
                    onClick={() => onRedesign(issue.id)}
                    className="btn btn-ghost"
                    style={{ padding: '5px 10px', fontSize: '0.75rem' }}
                  >
                    Flag for Manual Redesign
                  </button>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
};

export default IssueCard;
