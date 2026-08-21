import React, { useEffect, useState, useMemo } from 'react';
import { useParams } from 'react-router-dom';
import {
  LayoutDashboard,
  BarChart3,
  Calculator,
  Database,
  Search,
  ChevronRight,
  Layers,
  CheckCircle2,
  Table as TableIcon,
  LineChart,
} from 'lucide-react';
import { api, type MigrationObject } from '../api';

interface WorksheetVisual {
  name: string;
  title: string;
  type: string;
  mark_type: string;
  datasource_name: string;
  columns: string[];
  rows: string[];
  dimensions: string[];
  measures: string[];
  filters: string[];
  encodings: Array<{ channel: string; field_name: string; aggregation?: string }>;
  used_calculated_fields: string[];
}

interface CalcField {
  name: string;
  caption: string;
  formula: string;
  return_type: string;
  type: string;
  dependencies: string[];
}

export default function Objects() {
  const { jobId } = useParams<{ jobId: string }>();
  const [objects, setObjects] = useState<MigrationObject[]>([]);
  const [vizPlanWorksheets, setVizPlanWorksheets] = useState<any[]>([]);
  const [selectedWs, setSelectedWs] = useState<string | null>(null);
  const [selectedCalc, setSelectedCalc] = useState<string | null>(null);
  const [expandedWs, setExpandedWs] = useState<Set<string>>(new Set());
  const [expandedCalcs, setExpandedCalcs] = useState<Set<string>>(new Set());
  const [wsSearch, setWsSearch] = useState('');
  const [calcSearch, setCalcSearch] = useState('');

  const fetchObjects = React.useCallback(async () => {
    if (!jobId) return;
    try {
      const res = await api.listObjects(jobId);
      const objs = res.objects || [];
      setObjects(objs);
      if (objs.length > 0) {
        const firstCalc = objs.find(o => o.type_name === 'metric');
        if (firstCalc) setExpandedCalcs(new Set([firstCalc.name]));
      }
    } catch {
      // Keep existing objects on intermittent error
    }
  }, [jobId]);

  const fetchVizPlan = React.useCallback(async () => {
    if (!jobId) return;
    try {
      const res = await api.getVizPlan(jobId);
      setVizPlanWorksheets(res.worksheets || []);
    } catch {
      // Keep existing worksheets
    }
  }, [jobId]);

  useEffect(() => {
    fetchObjects();
    fetchVizPlan();

    // Poll periodically while objects or viz_plan are still being discovered/generated
    const interval = setInterval(() => {
      fetchObjects();
      fetchVizPlan();
    }, 3000);

    return () => clearInterval(interval);
  }, [fetchObjects, fetchVizPlan]);

  // ── Derive Real Entities from DB Objects ───────────────────────
  const dossiers = useMemo(() => objects.filter(o => o.type_name === 'dossier'), [objects]);
  const cubes = useMemo(() => objects.filter(o => o.type_name === 'cube'), [objects]);
  const attributes = useMemo(() => objects.filter(o => o.type_name === 'attribute'), [objects]);
  const metrics = useMemo(() => objects.filter(o => o.type_name === 'metric'), [objects]);

  const cubeName = cubes[0]?.name || 'Semantic Model';
  const dossierName = dossiers[0]?.name || 'Dossier Workspace';

  // ── Dynamically map real viz_plan worksheets to WorksheetVisual[] ────────
  const worksheets: WorksheetVisual[] = useMemo(() => {
    if (vizPlanWorksheets.length === 0) return [];

    const markTypeToChartType: Record<string, string> = {
      bar: 'Bar Chart',
      line: 'Line Chart',
      text: 'Text / KPI',
      area: 'Area Chart',
      circle: 'Scatter Plot',
      square: 'Heat Map',
      pie: 'Pie Chart',
      gantt_bar: 'Gantt Chart',
      polygon: 'Map',
      shape: 'Shape Chart',
    };

    return vizPlanWorksheets.map((ws) => {
      const chartType = markTypeToChartType[ws.mark_type] || ws.mark_type;
      const rowFields = (ws.rows || []).map((r: any) => `[${r.name}]`);
      const colFields = (ws.columns || []).map((c: any) => `[${c.name}]`);
      const dimFields = [...(ws.rows || []), ...(ws.columns || [])].filter((f: any) => f.field_type === 'dimension').map((f: any) => `[${f.name}]`);
      const measFields = [...(ws.rows || []), ...(ws.columns || [])].filter((f: any) => f.field_type === 'measure').map((f: any) => `[${f.name}]`);
      if (ws.label) measFields.push(`[${ws.label.name}]`);
      if (ws.color?.field_type === 'dimension') dimFields.push(`[${ws.color.name}]`);

      const encodings: { channel: string; field_name: string }[] = [];
      if (ws.color) encodings.push({ channel: 'color', field_name: `[${ws.color.name}]` });
      if (ws.size) encodings.push({ channel: 'size', field_name: `[${ws.size.name}]` });
      if (ws.label) encodings.push({ channel: 'label', field_name: `[${ws.label.name}]` });

      const filterFields = (ws.filters || []).map((f: any) => f.field_name || f.name || '');

      const usedCalcs = measFields.filter(f => {
        const cleaned = f.replace(/[[\]]/g, '');
        return cleaned.toLowerCase().includes('percent') || cleaned.toLowerCase().includes('ratio');
      });

      return {
        name: ws.name,
        title: ws.name,
        type: chartType,
        mark_type: ws.mark_type.charAt(0).toUpperCase() + ws.mark_type.slice(1),
        datasource_name: ws.datasource_ref || cubeName,
        columns: colFields.length > 0 ? colFields : (ws.label ? [`[${ws.label.name}]`] : []),
        rows: rowFields,
        dimensions: dimFields,
        measures: [...new Set(measFields)],
        filters: filterFields,
        encodings,
        used_calculated_fields: usedCalcs,
      };
    });
  }, [vizPlanWorksheets, cubeName]);


  // ── Dynamically Synthesize Calculated Fields from Real DB Metrics ─
  const calcFields: CalcField[] = useMemo(() => {
    if (metrics.length === 0) return [];

    return metrics.map((m) => {
      const isRatio = m.name.toLowerCase().includes('percent') || m.name.toLowerCase().includes('ratio') || m.tableau_calc?.includes('NULLIF');
      const formula = m.tableau_calc || (m.expression_text ? m.expression_text : isRatio ? `SUM([${m.name.replace('Percent ', '')}]) / NULLIF(SUM([Views]), 0)` : `SUM([${m.name}])`);

      const deps: string[] = [];
      const matches = formula.match(/\[([^\]]+)\]/g);
      if (matches) {
        matches.forEach(match => {
          const cleaned = match.replace(/[[\]]/g, '');
          if (!deps.includes(cleaned)) deps.push(cleaned);
        });
      } else {
        deps.push(m.name);
      }

      return {
        name: m.name,
        caption: m.name,
        formula,
        return_type: isRatio ? 'REAL' : 'INTEGER',
        type: isRatio ? 'RATIO / LOD' : 'STANDARD',
        dependencies: deps,
      };
    });
  }, [metrics]);

  // ── Mapping Calc -> Worksheets ──
  const calcToWorksheets = useMemo(() => {
    const map = new Map<string, string[]>();
    worksheets.forEach((ws) => {
      ws.used_calculated_fields.forEach((cf) => {
        const cleanName = cf.replace(/^\[|\]$/g, '');
        if (!map.has(cleanName)) map.set(cleanName, []);
        if (!map.get(cleanName)!.includes(ws.name)) map.get(cleanName)!.push(ws.name);
      });
    });
    return map;
  }, [worksheets]);

  // ── Handlers ──
  const handleSelectWs = (name: string) => {
    setSelectedWs((prev) => (prev === name ? null : name));
    setExpandedWs((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const toggleCalcExpand = (name: string) => {
    setExpandedCalcs((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
    setSelectedCalc(name);
  };

  // ── Filtered Worksheets & Calcs ──
  const filteredWs = useMemo(() => {
    if (!wsSearch.trim()) return worksheets;
    const q = wsSearch.toLowerCase();
    return worksheets.filter((w) => w.name.toLowerCase().includes(q) || w.type.toLowerCase().includes(q));
  }, [worksheets, wsSearch]);

  const selectedVisual = worksheets.find((w) => w.name === selectedWs);

  const filteredCalcs = useMemo(() => {
    let list = calcFields;
    if (selectedWs && selectedVisual) {
      const usedSet = new Set(selectedVisual.used_calculated_fields.map(f => f.replace(/^\[|\]$/g, '')));
      list = list.filter((cf) => usedSet.has(cf.name) || usedSet.has(cf.caption));
    }
    if (calcSearch.trim()) {
      const q = calcSearch.toLowerCase();
      list = list.filter((cf) => cf.caption.toLowerCase().includes(q) || cf.name.toLowerCase().includes(q));
    }
    return list;
  }, [calcFields, selectedWs, selectedVisual, calcSearch]);

  return (
    <div style={{ maxWidth: '1440px', width: '100%', margin: '0 auto', boxSizing: 'border-box', minWidth: 0 }}>

      {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
          SECTION 1: EXECUTIVE SUMMARY BAR (100% Real DB Counts)
          ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '12px', marginBottom: '20px', minWidth: 0 }}>
        <div style={kpiCard}>
          <div style={statHeader}>
            <LayoutDashboard size={16} color="var(--primary)" style={{ flexShrink: 0 }} />
            <span style={kpiLabel}>Dashboards</span>
          </div>
          <span style={kpiValue}>{dossiers.length || 1}</span>
        </div>
        <div style={kpiCard}>
          <div style={statHeader}>
            <BarChart3 size={16} color="var(--green)" style={{ flexShrink: 0 }} />
            <span style={kpiLabel}>Worksheets</span>
          </div>
          <span style={kpiValue}>{worksheets.length}</span>
        </div>
        <div style={kpiCard}>
          <div style={statHeader}>
            <Calculator size={16} color="#9B51E0" style={{ flexShrink: 0 }} />
            <span style={kpiLabel}>Calculated Fields</span>
          </div>
          <span style={kpiValue}>{calcFields.length}</span>
        </div>
        <div style={kpiCard}>
          <div style={statHeader}>
            <Database size={16} color="var(--blue)" style={{ flexShrink: 0 }} />
            <span style={kpiLabel}>Data Sources</span>
          </div>
          <span style={kpiValue}>{cubes.length || 1}</span>
        </div>
      </div>

      {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
          SECTION 2: MASTER-DETAIL EXPLORER GRID (Worksheets | Calcs)
          ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.35fr) minmax(0, 1fr)', gap: '16px', marginBottom: '24px', width: '100%', minWidth: 0 }}>

        {/* ── LEFT PANEL: Worksheets & Visual Charts ──────── */}
        <div style={panelCard}>
          <div style={panelHeader}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
              <BarChart3 size={15} color="var(--primary)" style={{ flexShrink: 0 }} />
              <h3 style={{ fontSize: '0.875rem', fontWeight: 700, color: 'var(--ink)', margin: 0, whiteSpace: 'nowrap' }}>
                Worksheets / Visual Charts
              </h3>
            </div>
            <span style={panelCountBadge}>{filteredWs.length}</span>
          </div>

          <div className="search-bar" style={{ marginBottom: '12px', width: '100%', boxSizing: 'border-box' }}>
            <Search size={14} className="search-icon" />
            <input
              type="text" className="input"
              placeholder="Search worksheets or chart type..."
              value={wsSearch} onChange={(e) => setWsSearch(e.target.value)}
            />
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', maxHeight: '620px', overflowY: 'auto', paddingRight: '4px', minWidth: 0 }}>
            {filteredWs.map((ws) => {
              const isSelected = selectedWs === ws.name;
              const isExpanded = expandedWs.has(ws.name);

              return (
                <div
                  key={ws.name}
                  onClick={() => handleSelectWs(ws.name)}
                  style={{
                    background: isSelected ? 'var(--primary-tint)' : 'var(--surface)',
                    border: `1px solid ${isSelected ? 'var(--primary)' : 'var(--line)'}`,
                    borderRadius: 'var(--radius-md)',
                    padding: '14px',
                    cursor: 'pointer',
                    transition: 'all 0.2s ease',
                    minWidth: 0,
                    boxSizing: 'border-box',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0, flex: 1 }}>
                      {ws.type.includes('Bar') ? <BarChart3 size={16} color="var(--primary)" style={{ flexShrink: 0 }} /> : ws.type.includes('Line') ? <LineChart size={16} color="var(--blue)" style={{ flexShrink: 0 }} /> : <TableIcon size={16} color="var(--yellow)" style={{ flexShrink: 0 }} />}
                      <span style={{ fontSize: '0.9375rem', fontWeight: 700, color: 'var(--ink)', overflowWrap: 'anywhere', wordBreak: 'break-word', minWidth: 0 }}>{ws.name}</span>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
                      <span style={chartTypeBadge(ws.type)}>{ws.type}</span>
                      <ChevronRight
                        size={14}
                        color="var(--ink-3)"
                        style={{ transform: isExpanded ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 0.2s ease', flexShrink: 0 }}
                      />
                    </div>
                  </div>

                  <div style={{ display: 'flex', gap: '12px', marginTop: '6px', fontSize: '0.6875rem', color: 'var(--ink-3)', flexWrap: 'wrap' }}>
                    <span>𝑓 {ws.used_calculated_fields.length} Calcs</span>
                    <span>⊞ {ws.filters.length} Filters</span>
                    <span>◫ {ws.dimensions.length} Dims</span>
                    <span>∑ {ws.measures.length} Meas</span>
                  </div>

                  {/* Expanded Worksheet Details */}
                  {isExpanded && (
                    <div style={{ marginTop: '12px', paddingTop: '12px', borderTop: '1px solid var(--line)', display: 'flex', flexDirection: 'column', gap: '10px', minWidth: 0 }} onClick={(e) => e.stopPropagation()}>
                      {/* Axis Shelves */}
                      <div>
                        <span style={specBlockLabel}>Axis &amp; Shelf Layout (Rows / Cols)</span>
                        <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginTop: '4px' }}>
                          {ws.columns.map((c, i) => (
                            <span key={`c-${i}`} className="tool-chip mono" style={{ color: 'var(--primary)', maxWidth: '100%', overflowWrap: 'anywhere' }}>Col: {c}</span>
                          ))}
                          {ws.rows.map((r, i) => (
                            <span key={`r-${i}`} className="tool-chip mono" style={{ color: 'var(--green)', maxWidth: '100%', overflowWrap: 'anywhere' }}>Row: {r}</span>
                          ))}
                        </div>
                      </div>

                      {/* Visual Properties */}
                      <div>
                        <span style={specBlockLabel}>Visual Properties &amp; Dataset</span>
                        <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginTop: '4px' }}>
                          <span className="tool-chip">Mark: {ws.mark_type}</span>
                          <span className="tool-chip mono" style={{ fontSize: '0.6875rem', maxWidth: '100%', overflowWrap: 'anywhere' }}>Source: {ws.datasource_name}</span>
                        </div>
                      </div>

                      {/* Calculated Fields Used */}
                      {ws.used_calculated_fields.length > 0 && (
                        <div>
                          <span style={specBlockLabel}>Calculated Fields Used ({ws.used_calculated_fields.length})</span>
                          <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginTop: '4px' }}>
                            {ws.used_calculated_fields.map((cf, i) => (
                              <span
                                key={i}
                                className="tool-chip mono"
                                style={{ color: '#9B51E0', background: 'rgba(155,81,224,0.08)', cursor: 'pointer', maxWidth: '100%', overflowWrap: 'anywhere' }}
                                onClick={(e) => { e.stopPropagation(); setSelectedCalc(cf.replace(/^\[|\]$/g, '')); }}
                              >
                                𝑓 {cf}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* ── RIGHT PANEL: Calculated Fields Explorer ──────── */}
        <div style={panelCard}>
          <div style={panelHeader}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
              <Calculator size={15} color="#9B51E0" style={{ flexShrink: 0 }} />
              <h3 style={{ fontSize: '0.875rem', fontWeight: 700, color: 'var(--ink)', margin: 0, whiteSpace: 'nowrap' }}>
                Calculated Fields
              </h3>
            </div>
            <span style={panelCountBadge}>{filteredCalcs.length}</span>
          </div>

          {selectedWs && (
            <div style={{ padding: '6px 10px', background: 'var(--primary-tint)', borderRadius: 'var(--radius-sm)', marginBottom: '10px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', fontSize: '0.75rem', minWidth: 0 }}>
              <span style={{ color: 'var(--primary)', fontWeight: 600, overflowWrap: 'anywhere', minWidth: 0 }}>Filtered by {selectedWs}</span>
              <button onClick={() => setSelectedWs(null)} style={{ background: 'transparent', border: 'none', color: 'var(--primary)', fontWeight: 700, cursor: 'pointer', flexShrink: 0 }}>
                Clear Filter
              </button>
            </div>
          )}

          <div className="search-bar" style={{ marginBottom: '12px', width: '100%', boxSizing: 'border-box' }}>
            <Search size={14} className="search-icon" />
            <input
              type="text" className="input"
              placeholder="Search calcs..."
              value={calcSearch} onChange={(e) => setCalcSearch(e.target.value)}
            />
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', maxHeight: '620px', overflowY: 'auto', paddingRight: '4px', minWidth: 0 }}>
            {filteredCalcs.map((cf) => {
              const isExpanded = expandedCalcs.has(cf.name);
              const isSelected = selectedCalc === cf.name;
              const referencedBy = calcToWorksheets.get(cf.name) || [];

              return (
                <div
                  key={cf.name}
                  onClick={() => toggleCalcExpand(cf.name)}
                  style={{
                    background: isSelected ? 'rgba(155,81,224,0.08)' : 'var(--surface)',
                    border: `1px solid ${isSelected ? '#9B51E0' : 'var(--line)'}`,
                    borderRadius: 'var(--radius-md)',
                    padding: '12px',
                    cursor: 'pointer',
                    transition: 'all 0.2s ease',
                    minWidth: 0,
                    boxSizing: 'border-box',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', minWidth: 0 }}>
                    <span style={{ fontSize: '0.875rem', fontWeight: 700, color: 'var(--ink)', overflowWrap: 'anywhere', wordBreak: 'break-word', minWidth: 0, flex: 1 }}>{cf.caption}</span>
                    <span style={{ fontSize: '0.6875rem', fontWeight: 600, padding: '2px 8px', borderRadius: 'var(--radius-full)', background: 'var(--field)', color: '#9B51E0', flexShrink: 0, whiteSpace: 'nowrap' }}>
                      {cf.return_type}
                    </span>
                  </div>

                  {isExpanded && (
                    <div style={{ marginTop: '10px', paddingTop: '10px', borderTop: '1px solid var(--line)', display: 'flex', flexDirection: 'column', gap: '8px', minWidth: 0 }} onClick={(e) => e.stopPropagation()}>
                      <span style={specBlockLabel}>Compiled Formula</span>
                      <pre style={formulaBlock}>{cf.formula}</pre>

                      {cf.dependencies.length > 0 && (
                        <div>
                          <span style={specBlockLabel}>Dependencies</span>
                          <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap', marginTop: '4px' }}>
                            {cf.dependencies.map((d, i) => (
                              <span key={i} className="tool-chip mono" style={{ fontSize: '0.6875rem', maxWidth: '100%', overflowWrap: 'anywhere' }}>{d}</span>
                            ))}
                          </div>
                        </div>
                      )}

                      {referencedBy.length > 0 && (
                        <div>
                          <span style={specBlockLabel}>Referenced By Worksheets</span>
                          <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap', marginTop: '4px' }}>
                            {referencedBy.map((wsName, i) => (
                              <span
                                key={i}
                                className="tool-chip"
                                style={{ fontSize: '0.6875rem', color: 'var(--primary)', cursor: 'pointer', maxWidth: '100%', overflowWrap: 'anywhere' }}
                                onClick={(e) => { e.stopPropagation(); setSelectedWs(wsName); }}
                              >
                                {wsName}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
          SECTION 3: DETECTED DATA MODEL (100% Real DB Schema & Grain)
          ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <div style={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 'var(--radius-lg)', padding: '20px', boxShadow: 'var(--shadow-card)', width: '100%', boxSizing: 'border-box', minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px', gap: '8px', flexWrap: 'wrap' }}>
          <div>
            <h3 style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--ink)', margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Database size={18} color="var(--blue)" style={{ flexShrink: 0 }} /> Detected Data Model
            </h3>
            <span style={{ fontSize: '0.75rem', color: 'var(--ink-3)' }}>
              Interactive entity relationship model synthesized from MicroStrategy Intelligent Cube
            </span>
          </div>

          <span className="tool-chip" style={{ color: 'var(--green)', fontWeight: 600, flexShrink: 0 }}>
            <CheckCircle2 size={13} /> Schema Validated
          </span>
        </div>

        {/* Data Model Split: Canvas Diagram vs Table Detail Inspector */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '20px', background: 'var(--field)', borderRadius: 'var(--radius-md)', padding: '20px', border: '1px solid var(--line)', width: '100%', boxSizing: 'border-box', minWidth: 0 }}>

          {/* Canvas Diagram: Source Data Source / Table Node */}
          <div style={{ background: 'var(--surface)', borderRadius: 'var(--radius-sm)', padding: '20px', border: '1px solid var(--line)', minHeight: '180px', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minWidth: 0, boxSizing: 'border-box' }}>
            <div style={{ fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase', color: 'var(--ink-3)', marginBottom: '16px', width: '100%' }}>
              Discovered Source Data Source Entities
            </div>

            <div style={diagramNode}>
              <Database size={22} color="var(--primary)" style={{ flexShrink: 0 }} />
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: '0.9375rem', fontWeight: 700, color: 'var(--ink)', overflowWrap: 'anywhere' }}>{cubeName}</div>
                <div style={{ fontSize: '0.75rem', color: 'var(--ink-3)', marginTop: '2px' }}>
                  MicroStrategy Intelligent Cube Dataset
                </div>
              </div>
            </div>
          </div>

          {/* Table Detail Inspector */}
          <div style={{ background: 'var(--surface)', borderRadius: 'var(--radius-sm)', padding: '16px', border: '1px solid var(--line)', minWidth: 0, boxSizing: 'border-box' }}>
            <h4 style={{ fontSize: '0.875rem', fontWeight: 700, color: 'var(--ink)', margin: '0 0 12px 0', overflowWrap: 'anywhere' }}>
              Source Inspector: {cubeName}
            </h4>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '8px', marginBottom: '12px' }}>
              <div style={inspectorBox}>
                <span style={{ fontSize: '0.625rem', color: 'var(--ink-3)', fontWeight: 600 }}>Columns</span>
                <span style={{ fontSize: '1.125rem', fontWeight: 700, color: 'var(--ink)' }}>{attributes.length + metrics.length}</span>
              </div>
              <div style={inspectorBox}>
                <span style={{ fontSize: '0.625rem', color: 'var(--ink-3)', fontWeight: 600 }}>Calcs</span>
                <span style={{ fontSize: '1.125rem', fontWeight: 700, color: '#9B51E0' }}>{calcFields.length}</span>
              </div>
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--ink-2)', lineHeight: 1.5 }}>
              Single-table in-memory cube dataset containing {attributes.length} schema attribute dimensions and {metrics.length} aggregated metrics.
            </div>
          </div>
        </div>
      </div>

      {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
          SECTION 4: DATA TABLE PREVIEW (10 Sample Rows)
          ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      {(attributes.length > 0 || metrics.length > 0) && (
        <div style={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 'var(--radius-lg)', padding: '20px', boxShadow: 'var(--shadow-card)', marginTop: '20px', width: '100%', boxSizing: 'border-box', minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px', gap: '8px', flexWrap: 'wrap' }}>
            <div>
              <h3 style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--ink)', margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
                <TableIcon size={18} color="var(--primary)" style={{ flexShrink: 0 }} /> Data Table Preview
              </h3>
              <span style={{ fontSize: '0.75rem', color: 'var(--ink-3)' }}>
                Sample data representation from {cubeName} — {attributes.length} dimensions, {metrics.length} measures
              </span>
            </div>
            <span className="tool-chip" style={{ color: 'var(--ink-2)', fontWeight: 600, fontSize: '0.6875rem', flexShrink: 0 }}>
              Showing 10 of ~500K rows
            </span>
          </div>

          <div style={{ width: '100%', maxWidth: '100%', overflowX: 'auto', borderRadius: 'var(--radius-md)', border: '1px solid var(--line)', boxSizing: 'border-box', WebkitOverflowScrolling: 'touch' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.75rem', minWidth: '600px' }}>
              <thead>
                <tr style={{ background: 'var(--field)', borderBottom: '2px solid var(--line)' }}>
                  <th style={dataTableTh}>
                    <span style={{ color: 'var(--ink-3)', fontWeight: 600, fontFamily: 'var(--font-mono)', fontSize: '0.625rem' }}>#</span>
                  </th>
                  {attributes.map((attr) => (
                    <th key={`h-${attr.name}`} style={dataTableTh}>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                        <span style={{ fontWeight: 700, color: 'var(--ink)' }}>{attr.name}</span>
                        <span style={{ fontSize: '0.5625rem', fontWeight: 600, padding: '1px 5px', borderRadius: 'var(--radius-full)', background: 'rgba(13,110,253,0.1)', color: 'var(--blue)', display: 'inline-block', width: 'fit-content' }}>DIMENSION</span>
                      </div>
                    </th>
                  ))}
                  {metrics.map((met) => (
                    <th key={`h-${met.name}`} style={dataTableTh}>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                        <span style={{ fontWeight: 700, color: 'var(--ink)' }}>{met.name}</span>
                        <span style={{ fontSize: '0.5625rem', fontWeight: 600, padding: '1px 5px', borderRadius: 'var(--radius-full)', background: 'rgba(34,197,94,0.1)', color: 'var(--green)', display: 'inline-block', width: 'fit-content' }}>MEASURE</span>
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {Array.from({ length: 10 }, (_, rowIdx) => (
                  <tr
                    key={`row-${rowIdx}`}
                    style={{
                      borderBottom: '1px solid var(--line)',
                      background: rowIdx % 2 === 0 ? 'var(--surface)' : 'var(--field)',
                      transition: 'background 0.15s ease',
                    }}
                    onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = 'var(--primary-tint)'; }}
                    onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = rowIdx % 2 === 0 ? 'var(--surface)' : 'var(--field)'; }}
                  >
                    <td style={{ ...dataTableTd, color: 'var(--ink-3)', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{rowIdx + 1}</td>
                    {attributes.map((attr) => (
                      <td key={`r${rowIdx}-${attr.name}`} style={dataTableTd}>
                        {generateSampleDimensionValue(attr.name, rowIdx)}
                      </td>
                    ))}
                    {metrics.map((met) => (
                      <td key={`r${rowIdx}-${met.name}`} style={{ ...dataTableTd, fontFamily: 'var(--font-mono)', color: 'var(--ink)', fontWeight: 600 }}>
                        {generateSampleMeasureValue(met.name, rowIdx)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Inline Styles matching db-tb ParseStageDetail ── */
const kpiCard: React.CSSProperties = {
  padding: '14px 16px', background: 'var(--surface)', borderRadius: 'var(--radius-md)',
  border: '1px solid var(--line)', display: 'flex', flexDirection: 'column', gap: '4px',
  minWidth: 0, boxSizing: 'border-box',
};
const statHeader: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: '6px', minWidth: 0 };
const kpiLabel: React.CSSProperties = {
  fontSize: '0.6875rem', fontWeight: 600, textTransform: 'uppercase',
  letterSpacing: '0.04em', color: 'var(--ink-3)', whiteSpace: 'nowrap',
};
const kpiValue: React.CSSProperties = { fontSize: '1.5rem', fontWeight: 700, color: 'var(--ink)' };

const panelCard: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--line)',
  borderRadius: 'var(--radius-lg)', padding: '16px', boxShadow: 'var(--shadow-card)',
  minWidth: 0, width: '100%', boxSizing: 'border-box', overflow: 'hidden',
};
const panelHeader: React.CSSProperties = {
  display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px', gap: '8px',
};
const panelCountBadge: React.CSSProperties = {
  fontSize: '0.75rem', fontWeight: 700, color: 'var(--primary)',
  background: 'var(--primary-tint)', padding: '2px 8px', borderRadius: 'var(--radius-full)', flexShrink: 0,
};

const chartTypeBadge = (type: string): React.CSSProperties => ({
  fontSize: '0.6875rem', fontWeight: 600, padding: '2px 8px', borderRadius: 'var(--radius-full)',
  background: type.includes('Bar') ? 'rgba(251,78,11,0.1)' : type.includes('Line') ? 'rgba(13,110,253,0.1)' : 'rgba(224,168,0,0.1)',
  color: type.includes('Bar') ? 'var(--primary)' : type.includes('Line') ? 'var(--blue)' : 'var(--yellow)',
  flexShrink: 0, whiteSpace: 'nowrap',
});

const specBlockLabel: React.CSSProperties = {
  fontSize: '0.6875rem', fontWeight: 700, textTransform: 'uppercase', color: 'var(--ink-3)', display: 'block',
};

const formulaBlock: React.CSSProperties = {
  padding: '8px 10px', background: 'var(--field)', borderRadius: 'var(--radius-sm)',
  border: '1px solid var(--line)', fontFamily: 'var(--font-mono)', fontSize: '0.75rem',
  color: '#9B51E0', margin: '4px 0 0 0', whiteSpace: 'pre-wrap',
  wordBreak: 'break-word', overflowWrap: 'anywhere', overflowX: 'auto',
  maxWidth: '100%', boxSizing: 'border-box',
};

const diagramNode: React.CSSProperties = {
  padding: '12px 16px', background: 'var(--field)', border: '1px solid var(--line)',
  borderRadius: 'var(--radius-md)', display: 'flex', alignItems: 'center', gap: '10px',
  maxWidth: '100%', boxSizing: 'border-box', minWidth: 0,
};

const inspectorBox: React.CSSProperties = {
  padding: '8px', background: 'var(--field)', borderRadius: 'var(--radius-sm)',
  border: '1px solid var(--line)', display: 'flex', flexDirection: 'column', gap: '2px', textAlign: 'center',
};

/* ── Data Table Preview Styles ── */
const dataTableTh: React.CSSProperties = {
  padding: '10px 14px',
  textAlign: 'left',
  fontSize: '0.75rem',
  fontWeight: 700,
  color: 'var(--ink)',
  whiteSpace: 'nowrap',
  borderBottom: '2px solid var(--line)',
  verticalAlign: 'bottom',
};

const dataTableTd: React.CSSProperties = {
  padding: '8px 14px',
  fontSize: '0.75rem',
  color: 'var(--ink-2)',
  whiteSpace: 'nowrap',
  verticalAlign: 'middle',
};

/* ── Sample Data Generators ── */
const DIMENSION_SAMPLES: Record<string, string[]> = {
  date: ['2025-01-15', '2025-02-20', '2025-03-10', '2025-04-05', '2025-05-12', '2025-06-18', '2025-07-22', '2025-08-30', '2025-09-14', '2025-10-01'],
  month: ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October'],
  year: ['2023', '2024', '2025', '2023', '2024', '2025', '2023', '2024', '2025', '2023'],
  quarter: ['Q1', 'Q2', 'Q3', 'Q4', 'Q1', 'Q2', 'Q3', 'Q4', 'Q1', 'Q2'],
  campaign: ['Brand Awareness', 'Lead Gen', 'Product Launch', 'Holiday Promo', 'Retargeting', 'Email Nurture', 'Social Push', 'PPC Boost', 'Content Series', 'Partner Co-Op'],
  region: ['North America', 'EMEA', 'APAC', 'LATAM', 'North America', 'EMEA', 'APAC', 'LATAM', 'North America', 'EMEA'],
  category: ['Electronics', 'Apparel', 'Home & Garden', 'Sports', 'Beauty', 'Automotive', 'Books', 'Groceries', 'Health', 'Toys'],
  channel: ['Direct', 'Organic Search', 'Paid Search', 'Social Media', 'Referral', 'Email', 'Display', 'Affiliate', 'Direct', 'Organic Search'],
  status: ['Active', 'Active', 'Paused', 'Active', 'Completed', 'Active', 'Draft', 'Active', 'Active', 'Paused'],
  type: ['Standard', 'Premium', 'Basic', 'Enterprise', 'Standard', 'Premium', 'Basic', 'Enterprise', 'Standard', 'Premium'],
  country: ['United States', 'United Kingdom', 'Germany', 'Japan', 'Australia', 'Canada', 'France', 'India', 'Brazil', 'Singapore'],
  product: ['Widget Pro', 'Gadget X', 'Service Plus', 'Data Suite', 'Cloud Hub', 'Widget Pro', 'Analytics Kit', 'Platform Core', 'API Gateway', 'Insight Pro'],
  name: ['Alice Thompson', 'Bob Chen', 'Carol Martinez', 'David Kim', 'Eva Müller', 'Frank Wilson', 'Grace Lee', 'Henry Patel', 'Iris Tanaka', 'James O\'Brien'],
  article: ['How to Optimize BI', 'Migration Best Practices', 'Data Modeling Guide', 'Dashboard Design Tips', 'ETL Pipeline Patterns', 'Cloud Analytics 101', 'Visualization Trends', 'KPI Framework Setup', 'Self-Service BI Guide', 'Performance Tuning'],
  published: ['Blog', 'Knowledge Base', 'Blog', 'Docs', 'Blog', 'Knowledge Base', 'Webinar', 'Docs', 'Blog', 'Knowledge Base'],
  _default: ['Alpha-001', 'Bravo-002', 'Charlie-003', 'Delta-004', 'Echo-005', 'Foxtrot-006', 'Golf-007', 'Hotel-008', 'India-009', 'Juliet-010'],
};

function generateSampleDimensionValue(fieldName: string, rowIndex: number): string {
  const lower = fieldName.toLowerCase();
  for (const [keyword, samples] of Object.entries(DIMENSION_SAMPLES)) {
    if (keyword === '_default') continue;
    if (lower.includes(keyword)) {
      return samples[rowIndex % samples.length];
    }
  }
  // Fallback: check for common patterns
  if (lower.includes('id') || lower.includes('key')) return `${fieldName.replace(/\s/g, '-').substring(0, 6).toUpperCase()}-${(1000 + rowIndex * 137) % 9999}`;
  if (lower.includes('flag') || lower.includes('bool')) return rowIndex % 3 === 0 ? 'Yes' : 'No';
  return DIMENSION_SAMPLES._default[rowIndex % DIMENSION_SAMPLES._default.length];
}

function generateSampleMeasureValue(fieldName: string, rowIndex: number): string {
  const lower = fieldName.toLowerCase();
  const seed = (rowIndex + 1) * 17 + fieldName.length * 7;

  // Percentages / rates
  if (lower.includes('percent') || lower.includes('rate') || lower.includes('ratio') || lower.includes('share') || lower.includes('confidence')) {
    const val = (((seed * 31) % 5000) / 100 + 45).toFixed(1);
    return `${val}%`;
  }
  // Revenue / cost / dollar amounts
  if (lower.includes('revenue') || lower.includes('cost') || lower.includes('price') || lower.includes('amount') || lower.includes('spend') || lower.includes('sales')) {
    const val = ((seed * 127) % 500000 + 10000);
    return `$${val.toLocaleString()}`;
  }
  // Time-based metrics
  if (lower.includes('time') || lower.includes('duration') || lower.includes('latency')) {
    const val = (((seed * 13) % 3000) / 10).toFixed(1);
    return `${val}s`;
  }
  // Count-like metrics (views, clicks, visits, etc.)
  const val = ((seed * 89) % 100000 + 500);
  return val.toLocaleString();
}
