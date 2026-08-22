import React, { useState, useEffect } from 'react';
import {
  Sparkles,
  X,
  CheckCircle2,
  AlertTriangle,
  ArrowRight,
  Send,
  Loader2,
  HelpCircle,
  Code,
  ShieldCheck,
  Check,
  RefreshCw,
} from 'lucide-react';
import { api } from '../../api';

interface AlternativeCandidate {
  title: string;
  calc: string;
  confidence: number;
  reason: string;
}

interface AgentExplainerModalProps {
  isOpen: boolean;
  onClose: () => void;
  objectName: string;
  sourceFormula: string;
  currentTargetCalc: string;
  onApplyCalc?: (newCalc: string) => void;
}

export const AgentExplainerModal: React.FC<AgentExplainerModalProps> = ({
  isOpen,
  onClose,
  objectName,
  sourceFormula,
  currentTargetCalc,
  onApplyCalc,
}) => {
  const [loadingExplanation, setLoadingExplanation] = useState(true);
  const [explanationError, setExplanationError] = useState<string | null>(null);
  const [reasoning, setReasoning] = useState('');
  const [astBreakdown, setAstBreakdown] = useState<string[]>([]);
  const [tradeoffs, setTradeoffs] = useState('');
  const [alternatives, setAlternatives] = useState<AlternativeCandidate[]>([]);

  // Interactive Re-prompting state
  const [userPrompt, setUserPrompt] = useState('');
  const [retranslating, setRetranslating] = useState(false);
  const [retranslateError, setRetranslateError] = useState<string | null>(null);
  const [revisedResult, setRevisedResult] = useState<{
    calc: string;
    confidence: number;
    notes: string;
  } | null>(null);

  const fetchExplanation = React.useCallback(async () => {
    setLoadingExplanation(true);
    setExplanationError(null);
    try {
      const res = await api.explainTranslation({
        name: objectName,
        source_formula: sourceFormula,
        target_calc: currentTargetCalc,
      });
      setReasoning(res.reasoning || '');
      setAstBreakdown(res.ast_breakdown || []);
      setTradeoffs(res.tradeoffs || '');
      const rawAlts = res.alternatives || [];
      const mappedAlternatives: AlternativeCandidate[] = rawAlts.map((a: any, idx: number) => ({
        title: a.title || a.name || `Alternative Strategy ${idx + 1}`,
        calc: a.calc || a.formula || '',
        confidence: typeof a.confidence === 'number' ? a.confidence : 0.8,
        reason: a.reason || a.notes || 'Alternative translation evaluated by agent',
      }));
      setAlternatives(mappedAlternatives);
    } catch (err: any) {
      setExplanationError(
        err?.message || 'Unable to load AI explanation from backend (/agent/explain).'
      );
    } finally {
      setLoadingExplanation(false);
    }
  }, [objectName, sourceFormula, currentTargetCalc]);

  useEffect(() => {
    if (isOpen) {
      fetchExplanation();
    } else {
      setUserPrompt('');
      setRevisedResult(null);
      setExplanationError(null);
      setRetranslateError(null);
    }
  }, [isOpen, fetchExplanation]);

  const handleRetranslate = async () => {
    if (!userPrompt.trim()) return;
    setRetranslating(true);
    setRetranslateError(null);
    try {
      const res = await api.retranslateWithAI({
        name: objectName,
        source_formula: sourceFormula,
        current_calc: currentTargetCalc,
        user_prompt: userPrompt,
      });
      setRevisedResult({
        calc: res.revised_calc,
        confidence: res.confidence,
        notes: res.agent_notes,
      });
    } catch (e: any) {
      setRetranslateError(e?.message || 'Failed to retranslate with AI agent (/agent/retranslate).');
    } finally {
      setRetranslating(false);
    }
  };

  const handleApply = (calcToApply: string) => {
    onApplyCalc?.(calcToApply);
    onClose();
  };

  if (!isOpen) return null;

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <div
        className="drawer-panel"
        style={{ maxWidth: '680px' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Header */}
        <div className="drawer-header" style={{ background: 'var(--field)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div
              style={{
                width: '36px',
                height: '36px',
                borderRadius: 'var(--radius-md)',
                background: 'var(--primary-tint)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'var(--primary)',
              }}
            >
              <Sparkles size={20} />
            </div>
            <div>
              <h2 style={{ fontSize: '1.0625rem', fontWeight: 600, color: 'var(--ink)', margin: 0 }}>
                AI Translation Agent &amp; Reasoning Inspector
              </h2>
              <p style={{ fontSize: '0.75rem', color: 'var(--ink-2)', margin: '2px 0 0 0' }}>
                Object: <strong style={{ color: 'var(--ink)' }}>{objectName}</strong>
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--ink-2)',
              cursor: 'pointer',
              padding: '6px',
            }}
          >
            <X size={18} />
          </button>
        </div>

        {/* Modal Content */}
        <div className="drawer-content" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          {/* Source vs Target Display */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              gap: '12px',
              padding: '12px',
              background: 'var(--field)',
              borderRadius: 'var(--radius-md)',
              border: '1px solid var(--line)',
            }}
          >
            <div>
              <span style={{ fontSize: '0.6875rem', textTransform: 'uppercase', color: 'var(--ink-3)', fontWeight: 600 }}>
                MicroStrategy Source
              </span>
              <div
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '0.75rem',
                  color: 'var(--ink)',
                  marginTop: '4px',
                }}
              >
                {sourceFormula}
              </div>
            </div>
            <div>
              <span style={{ fontSize: '0.6875rem', textTransform: 'uppercase', color: 'var(--primary)', fontWeight: 600 }}>
                Current Tableau Translation
              </span>
              <div
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '0.75rem',
                  color: 'var(--green)',
                  fontWeight: 600,
                  marginTop: '4px',
                }}
              >
                {currentTargetCalc}
              </div>
            </div>
          </div>

          {/* Loading / Error / Chain of Thought Rationale */}
          {loadingExplanation ? (
            <div style={{ padding: '30px', textAlign: 'center', color: 'var(--ink-2)' }}>
              <Loader2 size={24} className="spin-icon" style={{ margin: '0 auto 10px auto' }} color="var(--primary)" />
              <p style={{ fontSize: '0.8125rem' }}>Agent is analyzing AST dimensionality and translation tradeoffs...</p>
            </div>
          ) : explanationError ? (
            <div
              style={{
                padding: '16px',
                background: 'rgba(239, 68, 68, 0.08)',
                borderRadius: 'var(--radius-md)',
                border: '1px solid rgba(239, 68, 68, 0.25)',
                display: 'flex',
                flexDirection: 'column',
                gap: '10px',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--red)' }}>
                <AlertTriangle size={18} />
                <strong style={{ fontSize: '0.875rem' }}>AI Explanation Unavailable</strong>
              </div>
              <p style={{ fontSize: '0.8125rem', color: 'var(--ink-2)', margin: 0, lineHeight: 1.5 }}>
                {explanationError}
              </p>
              <div>
                <button
                  type="button"
                  onClick={fetchExplanation}
                  className="btn btn-secondary"
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '6px',
                    padding: '6px 12px',
                    fontSize: '0.75rem',
                  }}
                >
                  <RefreshCw size={13} />
                  <span>Retry Explanation</span>
                </button>
              </div>
            </div>
          ) : (
            <>
              {/* Agent Rationale */}
              <div>
                <h4 style={{ fontSize: '0.8125rem', fontWeight: 600, color: 'var(--ink)', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: '8px' }}>
                  Agent Translation Rationale
                </h4>
                <p style={{ fontSize: '0.8125rem', color: 'var(--ink-2)', lineHeight: 1.5, margin: 0 }}>
                  {reasoning || 'No specific rationale returned by backend agent.'}
                </p>
              </div>

              {/* AST Parsing Breakdown */}
              {astBreakdown.length > 0 && (
                <div>
                  <h4 style={{ fontSize: '0.8125rem', fontWeight: 600, color: 'var(--ink)', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: '8px' }}>
                    AST Dependency Step-Through
                  </h4>
                  <div
                    style={{
                      background: 'var(--inset)',
                      borderRadius: 'var(--radius-sm)',
                      padding: '10px 14px',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '6px',
                      fontFamily: 'var(--font-mono)',
                      fontSize: '0.75rem',
                      color: 'var(--ink)',
                    }}
                  >
                    {astBreakdown.map((step, idx) => (
                      <div key={idx} style={{ display: 'flex', gap: '8px' }}>
                        <span style={{ color: 'var(--primary)' }}>&bull;</span>
                        <span>{step}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Tradeoff Explanation */}
              {tradeoffs && (
                <div
                  style={{
                    padding: '10px 14px',
                    background: 'var(--field)',
                    borderRadius: 'var(--radius-sm)',
                    border: '1px solid var(--line)',
                    fontSize: '0.75rem',
                    color: 'var(--ink-2)',
                  }}
                >
                  <strong style={{ color: 'var(--ink)' }}>Dimensionality Tradeoff:</strong> {tradeoffs}
                </div>
              )}

              {/* Interactive Agent Re-Prompting */}
              <div
                style={{
                  padding: '16px',
                  background: 'var(--field)',
                  borderRadius: 'var(--radius-lg)',
                  border: '1px solid var(--line-strong)',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                  <Sparkles size={16} color="var(--primary)" />
                  <h4 style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--ink)', margin: 0 }}>
                    Guide or Re-Prompt AI Agent
                  </h4>
                </div>
                <p style={{ fontSize: '0.75rem', color: 'var(--ink-3)', margin: '0 0 10px 0' }}>
                  Provide specific constraints (e.g. <em>"Translate using {`{INCLUDE [Region]}`} instead of FIXED"</em> or <em>"Add null coalescing ZN()"</em>)
                </p>

                <div style={{ display: 'flex', gap: '8px' }}>
                  <input
                    type="text"
                    className="input"
                    placeholder="Enter agent guidance prompt..."
                    value={userPrompt}
                    onChange={(e) => setUserPrompt(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleRetranslate()}
                    style={{ flex: 1, fontSize: '0.8125rem' }}
                  />
                  <button
                    onClick={handleRetranslate}
                    disabled={retranslating || !userPrompt.trim()}
                    className="btn btn-primary"
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '5px',
                      padding: '7px 14px',
                      fontSize: '0.75rem',
                      fontWeight: 600,
                    }}
                  >
                    {retranslating ? (
                      <Loader2 size={13} className="spin-icon" />
                    ) : (
                      <Send size={13} />
                    )}
                    <span>Re-Translate</span>
                  </button>
                </div>

                {/* Retranslate Error Alert */}
                {retranslateError && (
                  <div
                    style={{
                      marginTop: '10px',
                      padding: '10px 12px',
                      background: 'rgba(239, 68, 68, 0.08)',
                      borderRadius: 'var(--radius-sm)',
                      border: '1px solid rgba(239, 68, 68, 0.25)',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '8px',
                      color: 'var(--red)',
                      fontSize: '0.75rem',
                    }}
                  >
                    <AlertTriangle size={14} style={{ flexShrink: 0 }} />
                    <span>{retranslateError}</span>
                  </div>
                )}

                {/* Revised Translation Output */}
                {revisedResult && (
                  <div
                    style={{
                      marginTop: '12px',
                      padding: '12px',
                      background: 'var(--surface)',
                      borderRadius: 'var(--radius-md)',
                      border: '1px solid var(--primary)',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
                      <span style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--primary)' }}>
                        AI Generated Revision ({Math.round(revisedResult.confidence * 100)}% Confidence)
                      </span>
                      <button
                        onClick={() => handleApply(revisedResult.calc)}
                        className="btn btn-primary"
                        style={{ padding: '4px 10px', fontSize: '0.6875rem', fontWeight: 600 }}
                      >
                        Apply This Revision
                      </button>
                    </div>
                    <div
                      style={{
                        padding: '8px',
                        background: 'var(--inset)',
                        borderRadius: 'var(--radius-sm)',
                        fontFamily: 'var(--font-mono)',
                        fontSize: '0.75rem',
                        color: 'var(--green)',
                        fontWeight: 600,
                        marginBottom: '6px',
                      }}
                    >
                      {revisedResult.calc}
                    </div>
                    <div style={{ fontSize: '0.6875rem', color: 'var(--ink-2)' }}>
                      {revisedResult.notes}
                    </div>
                  </div>
                )}
              </div>

              {/* Alternative Candidate Strategies */}
              {alternatives.length > 0 && (
                <div>
                  <h4 style={{ fontSize: '0.8125rem', fontWeight: 600, color: 'var(--ink)', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: '10px' }}>
                    Alternative Candidate Strategies Evaluated
                  </h4>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                    {alternatives.map((alt, idx) => (
                      <div
                        key={idx}
                        style={{
                          padding: '12px',
                          background: 'var(--field)',
                          borderRadius: 'var(--radius-md)',
                          border: '1px solid var(--line)',
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
                          <span style={{ fontWeight: 600, fontSize: '0.8125rem', color: 'var(--ink)' }}>
                            {alt.title}
                          </span>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <span style={{ fontSize: '0.6875rem', fontWeight: 700, color: 'var(--ink-3)' }}>
                              {Math.round(alt.confidence * 100)}% match
                            </span>
                            <button
                              onClick={() => handleApply(alt.calc)}
                              className="btn btn-secondary"
                              style={{ padding: '3px 8px', fontSize: '0.6875rem' }}
                            >
                              Choose
                            </button>
                          </div>
                        </div>
                        <div
                          style={{
                            padding: '6px 8px',
                            background: 'var(--surface)',
                            borderRadius: 'var(--radius-sm)',
                            fontFamily: 'var(--font-mono)',
                            fontSize: '0.75rem',
                            color: 'var(--ink)',
                            marginBottom: '6px',
                          }}
                        >
                          {alt.calc}
                        </div>
                        <div style={{ fontSize: '0.6875rem', color: 'var(--ink-3)' }}>
                          {alt.reason}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default AgentExplainerModal;
