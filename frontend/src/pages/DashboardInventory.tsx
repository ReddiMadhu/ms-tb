import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  LayoutDashboard,
  BarChart3,
  CheckCircle2,
  Layers,
  Check,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  Copy,
} from 'lucide-react';
import { api } from '../api';
import { EmptyState } from '../components/ui/EmptyState';
import { TableauIcon } from '../components/icons/TableauIcon';
import styles from './DashboardInventory.module.css';

export interface MstrVisualDef {
  type?: string | null;
  rows: string[];
  columns: string[];
  color?: string | null;
  size?: string;
  angle?: string;
  label?: string;
  tooltip?: string[];
  filters?: string[];
  metrics?: string[];
  attributes?: string[];
}

export interface TableauVisualDef {
  markType: string;
  columnsShelf: string[];
  rowsShelf: string[];
  colorEncoding?: string | null;
  sizeEncoding?: string;
  labelEncoding?: string | null;
  tooltipShelf?: string[];
  filtersShelf?: string[];
  worksheetXmlSpec?: string;
}

export interface ConversionCardItem {
  id: string;
  worksheetName: string;
  chartType: string;
  status: 'SUCCESS' | 'MANUAL_REVIEW';
  failureReason?: string | null;
  mstrVisualType?: string | null;
  mstr: MstrVisualDef;
  tableau: TableauVisualDef;
}

export default function DashboardInventory() {
  const { jobId } = useParams<{ jobId: string }>();
  const [dossierName, setDossierName] = useState<string>('Dossier Inventory');
  const [visuals, setVisuals] = useState<ConversionCardItem[]>([]);
  const [expandedCardIds, setExpandedCardIds] = useState<Set<string>>(new Set());
  const [expandedSpecId, setExpandedSpecId] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const loadDashboardData = React.useCallback(async () => {
    if (!jobId) return;

    // Fetch dossier name from objects
    api.listObjects(jobId)
      .then((res) => {
        const objects = res.objects || [];
        const dossier = objects.find((o) => o.type_name === 'dossier');
        if (dossier) setDossierName(dossier.name);
      })
      .catch(() => {});

    // Fetch real worksheet cards from viz-plan
    try {
      const vizPlan = await api.getVizPlan(jobId);
      const ws = vizPlan.worksheets || [];
      if (ws.length === 0) {
        setVisuals([]);
        return;
      }

      const markToChart: Record<string, string> = {
        bar: 'Bar Chart',
        line: 'Line Chart',
        text: 'Text / KPI Card',
        area: 'Area Chart',
        circle: 'Scatter Plot',
        square: 'Heat Map',
        pie: 'Pie Chart',
        gantt_bar: 'Gantt Chart',
        polygon: 'Map',
      };

      const dynamicCards: ConversionCardItem[] = ws.map((w) => {
        // Guard: mark_type can be absent on auto-marked sheets.
        const rawMark = (w.mark_type || 'automatic').toLowerCase();
        const chartType = markToChart[rawMark] || `Auto (${rawMark})`;
        const rowNames = (w.rows || []).map((r: any) => `[${r.name}]`);
        const colNames = (w.columns || []).map((c: any) => `[${c.name}]`);
        const colorField = w.color ? `[${w.color.name}]` : null;
        const labelField = w.label ? `[${w.label.name}]` : null;
        const measNames = [...(w.rows || []), ...(w.columns || [])]
          .filter((f: any) => f.field_type === 'measure')
          .map((f: any) => f.name);
        if (w.label?.field_type === 'measure') measNames.push(w.label.name);
        const attrNames = [...(w.rows || []), ...(w.columns || [])]
          .filter((f: any) => f.field_type === 'dimension')
          .map((f: any) => f.name);
        if (w.color?.field_type === 'dimension') attrNames.push(w.color.name);

        const filterStrs = (w.filters || []).map((f: any) => `[${f.field_name}]`);
        // REAL harvested tooltip fields only — never synthesize from shelves.
        const tooltipReal = (w.tooltip_fields || []).map((t: any) => `[${t.name}]`);

        return {
          id: w.id,
          worksheetName: w.name,
          chartType,
          status: (w.is_failed ? 'MANUAL_REVIEW' : 'SUCCESS') as 'SUCCESS' | 'MANUAL_REVIEW',
          failureReason: (w as any).failure_reason || null,
          mstrVisualType: w.mstr_visual_type || null,
          mstr: {
            type: w.mstr_visual_type || null,
            columns: colNames,
            rows: rowNames,
            color: colorField,
            tooltip: tooltipReal,
            filters: filterStrs,
            metrics: [...new Set(measNames)],
            attributes: [...new Set(attrNames)],
          },
          tableau: {
            markType: rawMark.charAt(0).toUpperCase() + rawMark.slice(1),
            columnsShelf: colNames,
            rowsShelf: rowNames,
            colorEncoding: colorField,
            labelEncoding: labelField,
            tooltipShelf: tooltipReal,
            filtersShelf: filterStrs,
            worksheetXmlSpec: (() => {
              const enc: string[] = [];
              if (labelField) enc.push(`    <text column="${labelField}" /> <!-- Label shelf -->`);
              if (colorField) enc.push(`    <color column="${colorField}" /> <!-- Color shelf -->`);
              const encBlock = enc.length
                ? `\n    <encodings>\n${enc.join('\n')}\n    </encodings>`
                : '';
              return `<worksheet name="${w.name}">\n  <table>\n    <rows>${rowNames.join('')}</rows>\n    <cols>${colNames.join('')}</cols>${encBlock}\n  </table>\n</worksheet>`;
            })(),
          },
        };
      });

      if (dynamicCards.length > 0) {
        setVisuals(dynamicCards);
        // Expand first card by default, collapse remaining cards
        setExpandedCardIds(new Set([dynamicCards[0].id]));
      }
    } catch {
      // Keep existing
    }
  }, [jobId]);

  useEffect(() => {
    loadDashboardData();
  }, [loadDashboardData]);

  const toggleCard = (id: string) => {
    setExpandedCardIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const copySpec = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const totalVisuals = visuals.length;
  const successCount = visuals.filter((v) => v.status === 'SUCCESS').length;
  const parityRate = totalVisuals > 0 ? Math.round((successCount / totalVisuals) * 100) : 100;

  return (
    <div className={styles.container}>
      {/* ── Executive Conversion Summary Cards ───────────────────────── */}
      <div className={styles.summaryGrid}>
        <div className={styles.summaryCard}>
          <span className={styles.summaryLabel}>MSTR Source Dossier</span>
          <span className={styles.summaryValue} style={{ fontSize: '1.125rem', paddingTop: '4px' }}>
            {dossierName}
          </span>
        </div>
        <div className={styles.summaryCard}>
          <span className={styles.summaryLabel}>Planned Worksheets</span>
          <span className={styles.summaryValue}>{totalVisuals}</span>
        </div>
        <div className={styles.summaryCard}>
          <span className={styles.summaryLabel}>Tableau Worksheets</span>
          <span className={`${styles.summaryValue} ${styles.summaryValueSuccess}`}>{successCount}</span>
        </div>
        <div className={styles.summaryCard}>
          <span className={styles.summaryLabel}>Visual Conversion Parity</span>
          <span className={`${styles.summaryValue} ${styles.summaryValueSuccess}`}>{parityRate}%</span>
        </div>
      </div>

      {/* ── Visual Worksheets Content or Empty State ──────────────── */}
      {visuals.length === 0 ? (
        <div style={{ marginTop: '24px' }}>
          <EmptyState
            icon={LayoutDashboard}
            title="No visual conversion plans generated yet"
            description="Visual worksheets and conversion mappings will be generated once the pipeline completes the VIZ planning stage."
          />
        </div>
      ) : (
        <div className={styles.cardsList}>
          {visuals.map((card) => {
            const isCardExpanded = expandedCardIds.has(card.id);
            const isSpecExpanded = expandedSpecId === card.id;

            // Compute concise preview for collapsed state
            const shelfSummary = [
              card.tableau.columnsShelf.length > 0 ? `Cols: ${card.tableau.columnsShelf.join(', ')}` : null,
              card.tableau.rowsShelf.length > 0 ? `Rows: ${card.tableau.rowsShelf.join(', ')}` : null,
              card.tableau.colorEncoding ? `Color: ${card.tableau.colorEncoding}` : null,
              card.tableau.labelEncoding ? `Label: ${card.tableau.labelEncoding}` : null,
            ].filter(Boolean).join(' | ');

            return (
              <div key={card.id} className={styles.conversionCard}>
                {/* Clickable Accordion Card Header */}
                <div
                  className={`${styles.conversionCardHeader} ${styles.accordionHeader}`}
                  onClick={() => toggleCard(card.id)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      toggleCard(card.id);
                    }
                  }}
                  title={isCardExpanded ? 'Click to collapse' : 'Click to expand'}
                >
                  <div className={styles.cardTitleArea}>
                    <span className={styles.accordionChevron}>
                      {isCardExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                    </span>
                    <span className={styles.cardTitle}>{card.worksheetName}</span>
                    <span className={styles.visualTypeBadge}>{card.chartType}</span>
                    {!isCardExpanded && shelfSummary && (
                      <span className={styles.collapsedPreview}>{shelfSummary}</span>
                    )}
                  </div>
                  <div>
                    {card.status === 'SUCCESS' ? (
                      <span className={styles.statusBadgeSuccess}>
                        <CheckCircle2 size={13} /> Converted
                      </span>
                    ) : (
                      <span
                        className={styles.statusBadgeReview}
                        title={card.failureReason || undefined}
                      >
                        Review Needed
                      </span>
                    )}
                  </div>
                </div>

                {/* Expanded Card Content */}
                {isCardExpanded && (
                  <>
                    {/* Dual Column Side-by-Side Visual Comparison Body */}
                    <div className={styles.cardComparisonBody}>
                      {/* Left Column: MicroStrategy Visual Definition */}
                      <div className={styles.visualSideColumn}>
                        <div className={styles.columnHeader}>
                          <span className={`${styles.columnHeaderTitle} ${styles.mstrAccent}`}>
                            <Layers size={13} /> MicroStrategy Bindings
                          </span>
                        </div>

                        <div className={styles.fieldGroup}>
                          <div className={styles.fieldRow}>
                            <span className={styles.fieldLabel}>MSTR Visual Type:</span>
                            {card.mstrVisualType ? (
                              <span className={styles.fieldValue}>{card.mstrVisualType}</span>
                            ) : (
                              <span className={styles.fieldValue} style={{ fontStyle: 'italic', color: 'var(--ink-3)' }}>
                                No matching MSTR visual definition
                              </span>
                            )}
                          </div>
                          {card.mstr.columns.length > 0 && (
                            <div className={styles.fieldRow}>
                              <span className={styles.fieldLabel}>Columns Shelf:</span>
                              <div className={styles.fieldValue}>
                                {card.mstr.columns.map((c, i) => (
                                  <span key={i} className={`${styles.fieldTag} ${styles.fieldTagBlue}`}>
                                    {c}
                                  </span>
                                ))}
                              </div>
                            </div>
                          )}
                          {card.mstr.rows.length > 0 && (
                            <div className={styles.fieldRow}>
                              <span className={styles.fieldLabel}>Rows Shelf:</span>
                              <div className={styles.fieldValue}>
                                {card.mstr.rows.map((r, i) => (
                                  <span key={i} className={`${styles.fieldTag} ${styles.fieldTagBlue}`}>
                                    {r}
                                  </span>
                                ))}
                              </div>
                            </div>
                          )}
                          {card.mstr.color && (
                            <div className={styles.fieldRow}>
                              <span className={styles.fieldLabel}>Color Encoding:</span>
                              <span className={`${styles.fieldTag} ${styles.fieldTagBlue}`}>{card.mstr.color}</span>
                            </div>
                          )}
                          {card.mstr.metrics && card.mstr.metrics.length > 0 && (
                            <div className={styles.fieldRow}>
                              <span className={styles.fieldLabel}>Source Metrics:</span>
                              <div className={styles.fieldValue}>
                                {card.mstr.metrics.map((m, i) => (
                                  <span key={i} className={`${styles.fieldTag} ${styles.fieldTagPurple}`}>
                                    {m}
                                  </span>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      </div>

                      {/* Right Column: Tableau Equivalent Definition */}
                      <div className={styles.visualSideColumn}>
                        <div className={styles.columnHeader}>
                          <span className={`${styles.columnHeaderTitle} ${styles.tableauAccent}`}>
                            <TableauIcon size={14} /> Target Tableau Worksheet (VQL / XML)
                          </span>
                        </div>

                        <div className={styles.fieldGroup}>
                          <div className={styles.fieldRow}>
                            <span className={styles.fieldLabel}>Tableau Mark Type:</span>
                            <span className={styles.fieldValue} style={{ fontWeight: 600, color: 'var(--green, #22c55e)' }}>
                              {card.tableau.markType}
                            </span>
                          </div>
                          {card.tableau.columnsShelf.length > 0 && (
                            <div className={styles.fieldRow}>
                              <span className={styles.fieldLabel}>Columns Shelf:</span>
                              <div className={styles.fieldValue}>
                                {card.tableau.columnsShelf.map((c, i) => (
                                  <span key={i} className={`${styles.fieldTag} ${styles.fieldTagGreen}`}>
                                    {c}
                                  </span>
                                ))}
                              </div>
                            </div>
                          )}
                          {card.tableau.rowsShelf.length > 0 && (
                            <div className={styles.fieldRow}>
                              <span className={styles.fieldLabel}>Rows Shelf:</span>
                              <div className={styles.fieldValue}>
                                {card.tableau.rowsShelf.map((r, i) => (
                                  <span key={i} className={`${styles.fieldTag} ${styles.fieldTagGreen}`}>
                                    {r}
                                  </span>
                                ))}
                              </div>
                            </div>
                          )}
                          {card.tableau.colorEncoding && (
                            <div className={styles.fieldRow}>
                              <span className={styles.fieldLabel}>Color Shelf:</span>
                              <span className={`${styles.fieldTag} ${styles.fieldTagGreen}`}>{card.tableau.colorEncoding}</span>
                            </div>
                          )}
                          {card.tableau.labelEncoding && (
                            <div className={styles.fieldRow}>
                              <span className={styles.fieldLabel}>Label Shelf:</span>
                              <span className={`${styles.fieldTag} ${styles.fieldTagGreen}`}>{card.tableau.labelEncoding}</span>
                            </div>
                          )}
                        </div>
                      </div>
                    </div>

                    {/* Expandable Tableau XML Worksheet Spec */}
                    <div className={styles.specAccordion}>
                      <button
                        type="button"
                        className={styles.specTrigger}
                        onClick={(e) => {
                          e.stopPropagation();
                          setExpandedSpecId(isSpecExpanded ? null : card.id);
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                          <Layers size={14} style={{ color: 'var(--blue, #00a8cc)' }} />
                          <span>{isSpecExpanded ? 'Hide Generated Worksheet XML Spec' : 'Inspect Generated Tableau XML Spec'}</span>
                        </div>
                        {isSpecExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                      </button>

                      {isSpecExpanded && (
                        <div className={styles.specContent}>
                          <div className={styles.specHeader}>
                            <span className={styles.specTitle}>
                              Worksheet Shelf Schematic — from the migration plan. The emitted
                              .twb additionally carries datasource dependencies, panes and
                              encodings; download the workbook artifact for the full XML.
                            </span>
                            <button
                              type="button"
                              className={styles.specCopyBtn}
                              onClick={(e) => {
                                e.stopPropagation();
                                copySpec(card.tableau.worksheetXmlSpec || '', card.id);
                              }}
                            >
                              {copiedId === card.id ? (
                                <>
                                  <Check size={12} style={{ color: 'var(--green, #22c55e)' }} /> Copied
                                </>
                              ) : (
                                <>
                                  <Copy size={12} /> Copy Schematic
                                </>
                              )}
                            </button>
                          </div>
                          <pre className={styles.specPre}>
                            <code>{card.tableau.worksheetXmlSpec}</code>
                          </pre>
                        </div>
                      )}
                    </div>
                  </>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
