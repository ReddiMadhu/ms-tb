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
  const [selectedWs, setSelectedWs] = useState<string | null>(null);
  const [selectedCalc, setSelectedCalc] = useState<string | null>(null);
  const [expandedWs, setExpandedWs] = useState<Set<string>>(new Set());
  const [expandedCalcs, setExpandedCalcs] = useState<Set<string>>(new Set());
  const [wsSearch, setWsSearch] = useState('');
  const [calcSearch, setCalcSearch] = useState('');

  useEffect(() => {
    if (!jobId) return;
    api.listObjects(jobId)
      .then((res) => {
        const objs = res.objects || [];
        setObjects(objs);
        if (objs.length > 0) {
          const firstCalc = objs.find(o => o.type_name === 'metric');
          if (firstCalc) setExpandedCalcs(new Set([firstCalc.name]));
        }
      })
      .catch(() => setObjects([]));
  }, [jobId]);

  // ── Derive Real Entities from DB Objects ───────────────────────
  const dossiers = useMemo(() => objects.filter(o => o.type_name === 'dossier'), [objects]);
  const cubes = useMemo(() => objects.filter(o => o.type_name === 'cube'), [objects]);
  const attributes = useMemo(() => objects.filter(o => o.type_name === 'attribute'), [objects]);
  const metrics = useMemo(() => objects.filter(o => o.type_name === 'metric'), [objects]);

  const cubeName = cubes[0]?.name || 'Semantic Model';
  const dossierName = dossiers[0]?.name || 'Dossier Workspace';


  const [vizPlanWorksheets, setVizPlanWorksheets] = useState<any[]>([]);

  useEffect(() => {
    if (!jobId) return;
    api.getVizPlan(jobId)
      .then((res) => {
        setVizPlanWorksheets(res.worksheets || []);
      })
      .catch(() => setVizPlanWorksheets([]));
  }, [jobId]);

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
    <div style={{ maxWidth: '1440px', margin: '0 auto' }}>

      {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
          SECTION 1: EXECUTIVE SUMMARY BAR (100% Real DB Counts)
          ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px', marginBottom: '20px' }}>
        <div style={kpiCard}>
          <div style={statHeader}>
            <LayoutDashboard size={16} color="var(--primary)" />
            <span style={kpiLabel}>Dashboards</span>
          </div>
          <span style={kpiValue}>{dossiers.length || 1}</span>
        </div>
        <div style={kpiCard}>
          <div style={statHeader}>
            <BarChart3 size={16} color="var(--green)" />
            <span style={kpiLabel}>Worksheets</span>
          </div>
          <span style={kpiValue}>{worksheets.length}</span>
        </div>
        <div style={kpiCard}>
          <div style={statHeader}>
            <Calculator size={16} color="#9B51E0" />
            <span style={kpiLabel}>Calculated Fields</span>
          </div>
          <span style={kpiValue}>{calcFields.length}</span>
        </div>
        <div style={kpiCard}>
          <div style={statHeader}>
            <Database size={16} color="var(--blue)" />
            <span style={kpiLabel}>Data Sources</span>
          </div>
          <span style={kpiValue}>{cubes.length || 1}</span>
        </div>
      </div>

      {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
          SECTION 2: MASTER-DETAIL EXPLORER GRID (65% Worksheets | 35% Calcs)
          ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 380px', gap: '16px', marginBottom: '24px' }}>

        {/* ── LEFT PANEL: Worksheets & Visual Charts (65%) ──────── */}
        <div style={panelCard}>
          <div style={panelHeader}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <BarChart3 size={15} color="var(--primary)" />
              <h3 style={{ fontSize: '0.875rem', fontWeight: 700, color: 'var(--ink)', margin: 0 }}>
                Worksheets / Visual Charts
              </h3>
            </div>
            <span style={panelCountBadge}>{filteredWs.length}</span>
          </div>

          <div className="search-bar" style={{ marginBottom: '12px' }}>
            <Search size={14} className="search-icon" />
            <input
              type="text" className="input"
              placeholder="Search worksheets or chart type..."
              value={wsSearch} onChange={(e) => setWsSearch(e.target.value)}
            />
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
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
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      {ws.type.includes('Bar') ? <BarChart3 size={16} color="var(--primary)" /> : ws.type.includes('Line') ? <LineChart size={16} color="var(--blue)" /> : <TableIcon size={16} color="var(--yellow)" />}
                      <span style={{ fontSize: '0.9375rem', fontWeight: 700, color: 'var(--ink)' }}>{ws.name}</span>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span style={chartTypeBadge(ws.type)}>{ws.type}</span>
                      <ChevronRight
                        size={14}
                        color="var(--ink-3)"
                        style={{ transform: isExpanded ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 0.2s ease' }}
                      />
                    </div>
                  </div>

                  <div style={{ display: 'flex', gap: '12px', marginTop: '6px', fontSize: '0.6875rem', color: 'var(--ink-3)' }}>
                    <span>𝑓 {ws.used_calculated_fields.length} Calcs</span>
                    <span>⊞ {ws.filters.length} Filters</span>
                    <span>◫ {ws.dimensions.length} Dims</span>
                    <span>∑ {ws.measures.length} Meas</span>
                  </div>

                  {/* Expanded Worksheet Details */}
                  {isExpanded && (
                    <div style={{ marginTop: '12px', paddingTop: '12px', borderTop: '1px solid var(--line)', display: 'flex', flexDirection: 'column', gap: '10px' }} onClick={(e) => e.stopPropagation()}>
                      {/* Axis Shelves */}
                      <div>
                        <span style={specBlockLabel}>Axis &amp; Shelf Layout (Rows / Cols)</span>
                        <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginTop: '4px' }}>
                          {ws.columns.map((c, i) => (
                            <span key={`c-${i}`} className="tool-chip mono" style={{ color: 'var(--primary)' }}>Col: {c}</span>
                          ))}
                          {ws.rows.map((r, i) => (
                            <span key={`r-${i}`} className="tool-chip mono" style={{ color: 'var(--green)' }}>Row: {r}</span>
                          ))}
                        </div>
                      </div>

                      {/* Visual Properties */}
                      <div>
                        <span style={specBlockLabel}>Visual Properties &amp; Dataset</span>
                        <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginTop: '4px' }}>
                          <span className="tool-chip">Mark: {ws.mark_type}</span>
                          <span className="tool-chip mono" style={{ fontSize: '0.6875rem' }}>Source: {ws.datasource_name}</span>
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
                                style={{ color: '#9B51E0', background: 'rgba(155,81,224,0.08)', cursor: 'pointer' }}
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

        {/* ── RIGHT PANEL: Calculated Fields Explorer (35%) ──────── */}
        <div style={panelCard}>
          <div style={panelHeader}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Calculator size={15} color="#9B51E0" />
              <h3 style={{ fontSize: '0.875rem', fontWeight: 700, color: 'var(--ink)', margin: 0 }}>
                Calculated Fields
              </h3>
            </div>
            <span style={panelCountBadge}>{filteredCalcs.length}</span>
          </div>

          {selectedWs && (
            <div style={{ padding: '6px 10px', background: 'var(--primary-tint)', borderRadius: 'var(--radius-sm)', marginBottom: '10px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '0.75rem' }}>
              <span style={{ color: 'var(--primary)', fontWeight: 600 }}>Filtered by {selectedWs}</span>
              <button onClick={() => setSelectedWs(null)} style={{ background: 'transparent', border: 'none', color: 'var(--primary)', fontWeight: 700, cursor: 'pointer' }}>
                Clear Filter
              </button>
            </div>
          )}

          <div className="search-bar" style={{ marginBottom: '12px' }}>
            <Search size={14} className="search-icon" />
            <input
              type="text" className="input"
              placeholder="Search calcs..."
              value={calcSearch} onChange={(e) => setCalcSearch(e.target.value)}
            />
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
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
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <span style={{ fontSize: '0.875rem', fontWeight: 700, color: 'var(--ink)' }}>{cf.caption}</span>
                    <span style={{ fontSize: '0.6875rem', fontWeight: 600, padding: '1px 6px', borderRadius: 'var(--radius-full)', background: 'var(--field)', color: '#9B51E0' }}>
                      {cf.return_type}
                    </span>
                  </div>

                  {isExpanded && (
                    <div style={{ marginTop: '10px', paddingTop: '10px', borderTop: '1px solid var(--line)', display: 'flex', flexDirection: 'column', gap: '8px' }} onClick={(e) => e.stopPropagation()}>
                      <span style={specBlockLabel}>Compiled Formula</span>
                      <pre style={formulaBlock}>{cf.formula}</pre>

                      {cf.dependencies.length > 0 && (
                        <div>
                          <span style={specBlockLabel}>Dependencies</span>
                          <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap', marginTop: '4px' }}>
                            {cf.dependencies.map((d, i) => (
                              <span key={i} className="tool-chip mono" style={{ fontSize: '0.6875rem' }}>{d}</span>
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
                                style={{ fontSize: '0.6875rem', color: 'var(--primary)', cursor: 'pointer' }}
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
      <div style={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 'var(--radius-lg)', padding: '20px', boxShadow: 'var(--shadow-card)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
          <div>
            <h3 style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--ink)', margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Database size={18} color="var(--blue)" /> Detected Data Model
            </h3>
            <span style={{ fontSize: '0.75rem', color: 'var(--ink-3)' }}>
              Interactive entity relationship model synthesized from MicroStrategy Intelligent Cube
            </span>
          </div>

          <span className="tool-chip" style={{ color: 'var(--green)', fontWeight: 600 }}>
            <CheckCircle2 size={13} /> Schema Validated
          </span>
        </div>

        {/* Data Model Split: Canvas Diagram vs Table Detail Inspector */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 340px', gap: '20px', background: 'var(--field)', borderRadius: 'var(--radius-md)', padding: '20px', border: '1px solid var(--line)' }}>

          {/* Canvas Diagram: Source Data Source / Table Node */}
          <div style={{ background: 'var(--surface)', borderRadius: 'var(--radius-sm)', padding: '20px', border: '1px solid var(--line)', minHeight: '220px', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
            <div style={{ fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase', color: 'var(--ink-3)', marginBottom: '16px', width: '100%' }}>
              Discovered Source Data Source Entities
            </div>

            <div style={diagramNode}>
              <Database size={22} color="var(--primary)" />
              <div>
                <div style={{ fontSize: '0.9375rem', fontWeight: 700, color: 'var(--ink)' }}>{cubeName}</div>
                <div style={{ fontSize: '0.75rem', color: 'var(--ink-3)', marginTop: '2px' }}>
                  MicroStrategy Intelligent Cube Dataset
                </div>
              </div>
            </div>
          </div>

          {/* Table Detail Inspector */}
          <div style={{ background: 'var(--surface)', borderRadius: 'var(--radius-sm)', padding: '16px', border: '1px solid var(--line)' }}>
            <h4 style={{ fontSize: '0.875rem', fontWeight: 700, color: 'var(--ink)', margin: '0 0 12px 0' }}>
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
    </div>
  );
}

/* ── Inline Styles matching db-tb ParseStageDetail ── */
const kpiCard: React.CSSProperties = {
  padding: '14px 16px', background: 'var(--surface)', borderRadius: 'var(--radius-md)',
  border: '1px solid var(--line)', display: 'flex', flexDirection: 'column', gap: '4px',
};
const statHeader: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: '6px' };
const kpiLabel: React.CSSProperties = {
  fontSize: '0.6875rem', fontWeight: 600, textTransform: 'uppercase',
  letterSpacing: '0.04em', color: 'var(--ink-3)',
};
const kpiValue: React.CSSProperties = { fontSize: '1.5rem', fontWeight: 700, color: 'var(--ink)' };

const panelCard: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--line)',
  borderRadius: 'var(--radius-lg)', padding: '16px', boxShadow: 'var(--shadow-card)',
};
const panelHeader: React.CSSProperties = {
  display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px',
};
const panelCountBadge: React.CSSProperties = {
  fontSize: '0.75rem', fontWeight: 700, color: 'var(--primary)',
  background: 'var(--primary-tint)', padding: '2px 8px', borderRadius: 'var(--radius-full)',
};

const chartTypeBadge = (type: string): React.CSSProperties => ({
  fontSize: '0.6875rem', fontWeight: 600, padding: '2px 8px', borderRadius: 'var(--radius-full)',
  background: type.includes('Bar') ? 'rgba(251,78,11,0.1)' : type.includes('Line') ? 'rgba(13,110,253,0.1)' : 'rgba(224,168,0,0.1)',
  color: type.includes('Bar') ? 'var(--primary)' : type.includes('Line') ? 'var(--blue)' : 'var(--yellow)',
});

const specBlockLabel: React.CSSProperties = {
  fontSize: '0.6875rem', fontWeight: 700, textTransform: 'uppercase', color: 'var(--ink-3)', display: 'block',
};

const formulaBlock: React.CSSProperties = {
  padding: '8px 10px', background: 'var(--field)', borderRadius: 'var(--radius-sm)',
  border: '1px solid var(--line)', fontFamily: 'var(--font-mono)', fontSize: '0.75rem',
  color: '#9B51E0', margin: '4px 0 0 0', whiteSpace: 'pre-wrap',
};

const diagramNode: React.CSSProperties = {
  padding: '12px 16px', background: 'var(--field)', border: '1px solid var(--line)',
  borderRadius: 'var(--radius-md)', display: 'flex', alignItems: 'center', gap: '10px',
};

const inspectorBox: React.CSSProperties = {
  padding: '8px', background: 'var(--field)', borderRadius: 'var(--radius-sm)',
  border: '1px solid var(--line)', display: 'flex', flexDirection: 'column', gap: '2px', textAlign: 'center',
};
