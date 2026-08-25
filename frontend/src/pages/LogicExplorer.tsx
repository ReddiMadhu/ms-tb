import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  Sparkles,
  CheckCircle2,
  AlertTriangle,
  Copy,
  Check,
  Code2,
  ArrowRight,
  FileText,
  ChevronDown,
  ChevronRight,
} from 'lucide-react';
import { api, type MigrationObject } from '../api';
import styles from './LogicExplorer.module.css';

interface CalculationItem {
  id: string;
  name: string;
  category: 'LOD' | 'CONDITIONAL' | 'TABLE_CALC' | 'STANDARD';
  formulaType: string;
  sourceFormula: string;
  targetCalc: string;
  method: string;
  confidence: number;
  validationStatus: 'VALID' | 'WARNING' | 'FAIL';
  datasource: string;
  explanation: string;
  hasSource: boolean;
  hasTarget: boolean;
  mstrId?: string;
  aliasOf?: string;
}

export default function LogicExplorer() {
  const { jobId } = useParams<{ jobId: string }>();
  const [calculations, setCalculations] = useState<CalculationItem[]>([]);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [copiedIndex, setCopiedIndex] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const loadCalculations = React.useCallback(async () => {
    let targetJobId = jobId;
    if (!targetJobId) {
      try {
        const res = await api.listJobs();
        const jobList = res.jobs || [];
        if (jobList.length > 0) {
          targetJobId = jobList[0].id;
        }
      } catch {
        // Ignore job list error
      }
    }
    if (!targetJobId) {
      setIsLoading(false);
      return;
    }

    try {
      const res = await api.listObjects(targetJobId);
      const objects = res.objects || [];
      // In Logic Explorer, we focus specifically on translated business logic / calculated fields.
      // Base cube column metrics (which have no MSTR source formula and only apply default column subtotal SUM([Column]))
      // are physical dataset columns and belong in the Schema / Objects catalog, not in the Calculation explorer.
      const dynamicCalcs: CalculationItem[] = objects
        .filter((o) => {
          if (o.type_name !== 'metric' && !o.expression_text && !o.tableau_calc) return false;
          const srcRaw = (o.expression_text || '').trim();
          const tgtRaw = (o.tableau_calc || '').trim();
          // Filter out physical base column measures that lack an MSTR source formula
          // and are just default column aggregations (e.g. SUM([Column])).
          const isBaseColumnDefault = !srcRaw && (!tgtRaw || tgtRaw.toUpperCase() === `SUM([${(o.name || '').toUpperCase()}])`);
          if (isBaseColumnDefault) return false;
          return true;
        })
        .map((o: MigrationObject): CalculationItem => {
          const name = o.name;
          const srcRaw = (o.expression_text || '').trim();
          const tgtRaw = (o.tableau_calc || '').trim();
          const hasSource = srcRaw.length > 0;
          const hasTarget = tgtRaw.length > 0;

          // Structural classification only — no name-keyword guessing.
          const isLod = /\{\s*(FIXED|INCLUDE|EXCLUDE)\b/i.test(tgtRaw);
          const isTableCalc = /\b(RUNNING_|WINDOW_|LOOKUP\(|PREVIOUS_VALUE\(|INDEX\()/i.test(tgtRaw);
          const isConditional = /^\s*(IF\s|CASE\s)|\b(IF\s+[\[{]|CASE\s)/i.test(tgtRaw);

          const category: 'LOD' | 'CONDITIONAL' | 'TABLE_CALC' | 'STANDARD' = isLod
            ? 'LOD'
            : isTableCalc
            ? 'TABLE_CALC'
            : isConditional
            ? 'CONDITIONAL'
            : 'STANDARD';

          const formulaType = isLod
            ? 'LOD Expression'
            : isTableCalc
            ? 'Table Calculation'
            : isConditional
            ? 'Conditional Logic'
            : 'Standard Measure';

          return {
            id: o.id || o.mstr_id,
            name,
            category,
            formulaType,
            sourceFormula: srcRaw,
            targetCalc: tgtRaw,
            method: o.translation_method || 'translation method not recorded',
            confidence: typeof o.confidence === 'number' ? o.confidence : NaN,
            validationStatus: hasTarget ? ('VALID' as const) : ('WARNING' as const),
            datasource: 'MicroStrategy Schema',
            explanation: hasSource
              ? `Source formula quoted from MicroStrategy. Engine: ${o.translation_method || 'not recorded'}.`
              : 'MicroStrategy stores no formula for this base metric; the Tableau calc applies its default subtotal to the underlying column.',
            hasSource,
            hasTarget,
            mstrId: o.mstr_id,
          };
        });

      // Alias tagging: MSTR dossiers legitimately define several metric names
      // pointing at one expression. Same source+target ⇒ show the canonical partner.
      const byExpr = new Map<string, string>();
      for (const c of dynamicCalcs) {
        const key = `${c.sourceFormula}=>${c.targetCalc}`;
        if (!byExpr.has(key)) byExpr.set(key, c.name);
      }
      for (const c of dynamicCalcs) {
        const canonical = byExpr.get(`${c.sourceFormula}=>${c.targetCalc}`);
        if (canonical && canonical !== c.name) c.aliasOf = canonical;
      }

      if (dynamicCalcs.length > 0) {
        setCalculations(dynamicCalcs);
        // By default, expand only the first formula (index 0) so the user can easily browse without excessive scrolling
        setExpandedIds(new Set([dynamicCalcs[0].id]));
      }
    } catch {
      // Keep existing calculations on error
    } finally {
      setIsLoading(false);
    }
  }, [jobId]);

  useEffect(() => {
    loadCalculations();
  }, [loadCalculations]);

  const toggleCard = (id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const copyToClipboard = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedIndex(id);
    setTimeout(() => setCopiedIndex(null), 2000);
  };

  const totalCalculations = calculations.length;
  const validCount = calculations.filter((c) => c.validationStatus === 'VALID').length;
  const compilationRate = totalCalculations > 0 ? Math.round((validCount / totalCalculations) * 100) : 100;
  const lodCount = calculations.filter((c) => c.category === 'LOD').length;

  return (
    <div className={styles.container}>
      {/* ── Metric Header Grid ────────────────────────────────────────── */}
      <div className={styles.kpiGrid}>
        <div className={styles.kpiCard}>
          <span className={styles.kpiLabel}>MSTR Metric Calculations</span>
          <span className={styles.kpiValue}>{totalCalculations}</span>
        </div>
        <div className={styles.kpiCard}>
          <span className={styles.kpiLabel}>Tableau Calculated Fields (CF)</span>
          <span className={styles.kpiValue}>{validCount}</span>
        </div>
        <div className={styles.kpiCard}>
          <span className={styles.kpiLabel}>Logic Conversion Rate</span>
          <span className={styles.kpiValue} style={{ color: 'var(--green, #22c55e)' }}>
            {compilationRate}%
          </span>
        </div>
        <div className={styles.kpiCard}>
          <span className={styles.kpiLabel}>LOD / Dimty Expressions</span>
          <span className={styles.kpiValue}>{lodCount}</span>
        </div>
      </div>

      {/* ── Collapsible Calculation Cards List ────────────────────────── */}
      <div className={styles.cardsList}>
        {isLoading ? (
          <div className={styles.emptyState}>Loading calculation conversions...</div>
        ) : calculations.length === 0 ? (
          <div className={styles.emptyState}>No calculated fields found for this migration job.</div>
        ) : (
          calculations.map((item, idx) => {
            const isExpanded = expandedIds.has(item.id);
            const isWarn = item.validationStatus === 'WARNING';
            const isFail = item.validationStatus === 'FAIL';

            return (
              <div key={item.id || idx} className={styles.conversionCard}>
                {/* ── Clickable Card Header (Accordion) ── */}
                <div
                  className={`${styles.cardHeader} ${styles.cardHeaderClickable}`}
                  onClick={() => toggleCard(item.id)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      toggleCard(item.id);
                    }
                  }}
                >
                  <div className={styles.cardTitleGroup}>
                    <span className={styles.chevronIcon}>
                      {isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                    </span>
                    <span className={styles.cardFieldTitle}>{item.name}</span>
                    {item.formulaType && item.formulaType !== 'Standard Measure' && (
                      <span className={styles.formulaTypeBadge}>{item.formulaType}</span>
                    )}
                    {item.aliasOf && (
                      <span className={styles.aliasBadge}>
                        alias of [{item.aliasOf}]
                      </span>
                    )}
                    {!isExpanded && item.hasTarget && (
                      <span className={styles.collapsedPreview}>
                        <code>{item.targetCalc}</code>
                      </span>
                    )}
                  </div>
                  <div className={styles.cardStatusGroup}>
                    {isFail ? (
                      <span className={styles.statusBadgeWarn}>
                        <AlertTriangle size={13} /> Translation Failed
                      </span>
                    ) : isWarn ? (
                      <span className={styles.statusBadgeWarn}>
                        <AlertTriangle size={13} /> Requires Review
                      </span>
                    ) : (
                      <span className={styles.statusBadgeValid}>
                        <CheckCircle2 size={13} /> Valid
                      </span>
                    )}
                  </div>
                </div>

                {/* ── Expanded Content (Side-by-Side & Explanation) ── */}
                {isExpanded && (
                  <>
                    <div className={styles.sideBySideGrid}>
                      {/* Left: MicroStrategy Source */}
                      <div className={styles.codeColumn}>
                        <div className={styles.codeColumnHeader}>
                          <span className={styles.codeColumnTitleSource}>
                            <FileText size={13} /> MicroStrategy Metric Expression (Dimty / Formula)
                          </span>
                          {item.hasSource ? (
                            <button
                              type="button"
                              className={styles.copyBtn}
                              onClick={(e) => {
                                e.stopPropagation();
                                copyToClipboard(item.sourceFormula, `orig-${idx}`);
                              }}
                            >
                              {copiedIndex === `orig-${idx}` ? (
                                <>
                                  <Check size={12} style={{ color: 'var(--green, #22c55e)' }} /> Copied
                                </>
                              ) : (
                                <>
                                  <Copy size={12} /> Copy Formula
                                </>
                              )}
                            </button>
                          ) : null}
                        </div>
                        {item.hasSource ? (
                          <pre className={styles.codeBlock}>
                            <code>{item.sourceFormula}</code>
                          </pre>
                        ) : (
                          <pre className={styles.codeBlock}>
                            <code style={{ color: 'var(--ink-3)', fontStyle: 'italic' }}>
                              — no formula stored on this object. MicroStrategy defines base cube
                              metrics by their column alone; nothing was quoted because MSTR sent
                              nothing.
                            </code>
                          </pre>
                        )}
                      </div>

                      {/* Center: Arrow */}
                      <div className={styles.centerArrowDivider}>
                        <ArrowRight size={18} />
                        <span className={styles.arrowLabel}>Converted To</span>
                      </div>

                      {/* Right: Tableau Target */}
                      <div className={styles.codeColumn}>
                        <div className={styles.codeColumnHeader}>
                          <span className={styles.codeColumnTitleTarget}>
                            <Code2 size={13} /> Tableau Calculated Field (CF) / LOD Expression
                          </span>
                          {item.hasTarget ? (
                            <button
                              type="button"
                              className={styles.copyBtn}
                              onClick={(e) => {
                                e.stopPropagation();
                                copyToClipboard(item.targetCalc, `tgt-${idx}`);
                              }}
                            >
                              {copiedIndex === `tgt-${idx}` ? (
                                <>
                                  <Check size={12} style={{ color: 'var(--green, #22c55e)' }} /> Copied
                                </>
                              ) : (
                                <>
                                  <Copy size={12} /> Copy Calc
                                </>
                              )}
                            </button>
                          ) : null}
                        </div>
                        {item.hasTarget ? (
                          <pre className={`${styles.codeBlock} ${styles.codeBlockTarget}`}>
                            <code>{item.targetCalc}</code>
                          </pre>
                        ) : (
                          <pre className={`${styles.codeBlock} ${styles.codeBlockTarget}`}>
                            <code style={{ color: 'var(--ink-3)', fontStyle: 'italic' }}>
                              — no translated calc recorded for this object.
                            </code>
                          </pre>
                        )}
                      </div>
                    </div>

                    {item.explanation && (
                      <div className={styles.explanationFooter}>
                        <Sparkles size={14} className={styles.sparkleIcon} />
                        <span>
                          <strong>Transformation Note: </strong>
                          {item.explanation}
                        </span>
                      </div>
                    )}
                  </>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
