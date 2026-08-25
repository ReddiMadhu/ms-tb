import React, { useEffect, useState, useMemo } from 'react';
import { useParams } from 'react-router-dom';
import {
  LayoutDashboard,
  BookOpen,
  BarChart3,
  Calculator,
  Database,
  Search,
  ChevronRight,
  Table as TableIcon,
  LineChart,
  FileSpreadsheet,
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
  const [vizPlanDashboards, setVizPlanDashboards] = useState<any[]>([]);
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
    } catch {}
  }, [jobId]);

  const fetchVizPlan = React.useCallback(async () => {
    if (!jobId) return;
    try {
      const res = await api.getVizPlan(jobId);
      setVizPlanWorksheets(res.worksheets || []);
      setVizPlanDashboards(res.dashboards || []);
    } catch {}
  }, [jobId]);

  useEffect(() => {
    fetchObjects();
    fetchVizPlan();
  }, [fetchObjects, fetchVizPlan]);

  const isBaseColumnDefault = (m: MigrationObject) => {
    const calc = (m.tableau_calc || '').trim();
    const expr = (m.expression_text || '').trim();
    if (!expr || expr === '—' || expr === '-') {
      const calcMatch = calc.match(/^(?:SUM|AVG|COUNT|MIN|MAX)\(\[([^\]]+)\]\)$/i);
      if (calcMatch && calcMatch[1].trim().toLowerCase() === m.name.trim().toLowerCase()) {
        return true;
      }
    }
    return false;
  };

  const dossiers = useMemo(() => objects.filter(o => o.type_name === 'dossier'), [objects]);
  const cubes = useMemo(() => objects.filter(o => o.type_name === 'cube'), [objects]);

  const mstrPagesCount = useMemo(() => {
    if (vizPlanDashboards.length > 0) return vizPlanDashboards.length;
    const dossier = dossiers[0];
    if (dossier?.mstr_definition && typeof dossier.mstr_definition === 'object') {
      const defn = dossier.mstr_definition as any;
      let cnt = 0;
      for (const ch of defn.chapters || []) {
        cnt += (ch.pages || []).length || 1;
      }
      if (cnt > 0) return cnt;
    }
    return 3;
  }, [vizPlanDashboards, dossiers]);

  const uniqueAttributes = useMemo(() => {
    const seen = new Set<string>();
    const list: MigrationObject[] = [];
    for (const o of objects) {
      if (o.type_name === 'attribute') {
        const key = o.name.trim().toLowerCase();
        if (!seen.has(key)) {
          seen.add(key);
          list.push(o);
        }
      }
    }
    return list;
  }, [objects]);

  const baseMeasures = useMemo(() => {
    const seen = new Set<string>();
    const list: MigrationObject[] = [];
    for (const o of objects) {
      if (o.type_name === 'metric' && isBaseColumnDefault(o)) {
        const key = o.name.trim().toLowerCase();
        if (!seen.has(key)) {
          seen.add(key);
          list.push(o);
        }
      }
    }
    return list;
  }, [objects]);

  const derivedMetrics = useMemo(() => {
    const seen = new Set<string>();
    const list: MigrationObject[] = [];
    for (const o of objects) {
      if (o.type_name === 'metric' && !isBaseColumnDefault(o)) {
        const key = o.name.trim().toLowerCase();
        if (!seen.has(key)) {
          seen.add(key);
          list.push(o);
        }
      }
    }
    return list;
  }, [objects]);

  const cubeName = cubes[0]?.name || 'Claims';

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
        return cleaned.toLowerCase().includes('percent') || cleaned.toLowerCase().includes('ratio') || cleaned.toLowerCase().includes('avg');
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

  const calcFields: CalcField[] = useMemo(() => {
    if (derivedMetrics.length === 0) return [];

    return derivedMetrics.map((m) => {
      const isRatio = m.name.toLowerCase().includes('percent') || m.name.toLowerCase().includes('ratio') || m.tableau_calc?.includes('NULLIF');
      const formula = m.tableau_calc || m.expression_text || '(Translation pending)';

      const deps: string[] = [];
      if (formula !== '(Translation pending)') {
        const matches = formula.match(/\[([^\]]+)\]/g);
        if (matches) {
          matches.forEach(match => {
            const cleaned = match.replace(/[[\]]/g, '');
            if (!deps.includes(cleaned)) deps.push(cleaned);
          });
        }
      }
      if (deps.length === 0) deps.push(m.name);

      return {
        name: m.name,
        caption: m.name,
        formula,
        return_type: isRatio ? 'REAL' : 'INTEGER',
        type: isRatio ? 'RATIO / LOD' : 'CALCULATED',
        dependencies: deps,
      };
    });
  }, [derivedMetrics]);

  const sampleDataRows = useMemo(() => [
    {
      'Claim ID': 'CLM-2021000580',
      'Policy ID': 'POL-38914',
      'Line of Business': 'Commercial Auto',
      'Coverage': 'Collision',
      'Loss Cause': 'Rear-end Collision',
      'Claim Status': 'Closed',
      'Loss Date': '2021-04-12',
      'Reported Date': '2021-04-15',
      'State Name': 'Texas',
      'Region State': 'South',
      'Customer Age': 42,
      'Litigation': 'No',
      'Paid Amount USD': '$14,250.00',
      'Reserve Amount USD': '$0.00',
      'Recovery Amount USD': '$1,200.00',
      'Total Incurred USD': '$14,250.00',
      'Claim Resolution Time Days': 18,
      'Adjuster Name': 'Amanda Scott',
    },
    {
      'Claim ID': 'CLM-2021000884',
      'Policy ID': 'POL-19284',
      'Line of Business': 'Personal Auto',
      'Coverage': 'Comprehensive',
      'Loss Cause': 'Windshield Damage',
      'Claim Status': 'Closed',
      'Loss Date': '2021-05-20',
      'Reported Date': '2021-05-21',
      'State Name': 'California',
      'Region State': 'West',
      'Customer Age': 35,
      'Litigation': 'No',
      'Paid Amount USD': '$1,150.00',
      'Reserve Amount USD': '$0.00',
      'Recovery Amount USD': '$0.00',
      'Total Incurred USD': '$1,150.00',
      'Claim Resolution Time Days': 5,
      'Adjuster Name': 'Brian Martinez',
    },
    {
      'Claim ID': 'CLM-2021001249',
      'Policy ID': 'POL-55421',
      'Line of Business': 'Commercial Property',
      'Coverage': 'Property Damage',
      'Loss Cause': 'Water Leak',
      'Claim Status': 'Open',
      'Loss Date': '2021-06-03',
      'Reported Date': '2021-06-05',
      'State Name': 'Florida',
      'Region State': 'Southeast',
      'Customer Age': 58,
      'Litigation': 'Yes',
      'Paid Amount USD': '$8,400.00',
      'Reserve Amount USD': '$12,500.00',
      'Recovery Amount USD': '$0.00',
      'Total Incurred USD': '$20,900.00',
      'Claim Resolution Time Days': 45,
      'Adjuster Name': 'Carlos Rivera',
    },
    {
      'Claim ID': 'CLM-2021001890',
      'Policy ID': 'POL-78210',
      'Line of Business': 'Personal Auto',
      'Coverage': 'Bodily Injury',
      'Loss Cause': 'Intersection Impact',
      'Claim Status': 'In Review',
      'Loss Date': '2021-07-14',
      'Reported Date': '2021-07-16',
      'State Name': 'New York',
      'Region State': 'Northeast',
      'Customer Age': 29,
      'Litigation': 'Yes',
      'Paid Amount USD': '$28,900.00',
      'Reserve Amount USD': '$15,000.00',
      'Recovery Amount USD': '$5,400.00',
      'Total Incurred USD': '$43,900.00',
      'Claim Resolution Time Days': 64,
      'Adjuster Name': 'Amanda Scott',
    },
    {
      'Claim ID': 'CLM-2021002341',
      'Policy ID': 'POL-44109',
      'Line of Business': 'Homeowners',
      'Coverage': 'Dwelling',
      'Loss Cause': 'Hail Storm',
      'Claim Status': 'Closed',
      'Loss Date': '2021-08-01',
      'Reported Date': '2021-08-02',
      'State Name': 'Colorado',
      'Region State': 'West',
      'Customer Age': 47,
      'Litigation': 'No',
      'Paid Amount USD': '$9,750.00',
      'Reserve Amount USD': '$0.00',
      'Recovery Amount USD': '$0.00',
      'Total Incurred USD': '$9,750.00',
      'Claim Resolution Time Days': 12,
      'Adjuster Name': 'Brian Martinez',
    },
  ], []);

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
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '12px', marginBottom: '20px', minWidth: 0 }}>
        <div style={kpiCard}>
          <div style={statHeader}>
            <LayoutDashboard size={16} color="var(--primary)" style={{ flexShrink: 0 }} />
            <span style={kpiLabel}>MSTR Dossiers</span>
          </div>
          <span style={kpiValue}>{dossiers.length}</span>
        </div>
        <div style={kpiCard}>
          <div style={statHeader}>
            <BookOpen size={16} color="var(--blue)" style={{ flexShrink: 0 }} />
            <span style={kpiLabel}>MSTR Pages</span>
          </div>
          <span style={kpiValue}>{mstrPagesCount}</span>
        </div>
        <div style={kpiCard}>
          <div style={statHeader}>
            <BarChart3 size={16} color="var(--green)" style={{ flexShrink: 0 }} />
            <span style={kpiLabel}>MSTR Visualizations</span>
          </div>
          <span style={kpiValue}>{worksheets.length}</span>
        </div>
        <div style={kpiCard}>
          <div style={statHeader}>
            <Calculator size={16} color="#9B51E0" style={{ flexShrink: 0 }} />
            <span style={kpiLabel}>Derived Metrics</span>
          </div>
          <span style={kpiValue}>{calcFields.length}</span>
        </div>
        <div style={kpiCard}>
          <div style={statHeader}>
            <Database size={16} color="var(--blue)" style={{ flexShrink: 0 }} />
            <span style={kpiLabel}>Cube Attributes &amp; Measures</span>
          </div>
          <span style={kpiValue}>{uniqueAttributes.length + baseMeasures.length}</span>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.35fr) minmax(0, 1fr)', gap: '16px', marginBottom: '24px', width: '100%', minWidth: 0 }}>
        <div style={panelCard}>
          <div style={panelHeader}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
              <BarChart3 size={15} color="var(--primary)" style={{ flexShrink: 0 }} />
              <h3 style={{ fontSize: '0.875rem', fontWeight: 700, color: 'var(--ink)', margin: 0, whiteSpace: 'nowrap' }}>
                MSTR Visualizations
              </h3>
            </div>
            <span style={panelCountBadge}>{filteredWs.length}</span>
          </div>
          <div className="search-bar" style={{ marginBottom: '12px', width: '100%', boxSizing: 'border-box' }}>
            <Search size={14} className="search-icon" />
            <input type="text" className="input" placeholder="Search MicroStrategy visualizations..." value={wsSearch} onChange={(e) => setWsSearch(e.target.value)} />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', maxHeight: '620px', overflowY: 'auto', paddingRight: '4px', minWidth: 0 }}>
            {filteredWs.map((ws) => {
              const isSelected = selectedWs === ws.name;
              const isExpanded = expandedWs.has(ws.name);
              return (
                <div key={ws.name} onClick={() => handleSelectWs(ws.name)} style={{ background: isSelected ? 'var(--primary-tint)' : 'var(--surface)', border: `1px solid ${isSelected ? 'var(--primary)' : 'var(--line)'}`, borderRadius: 'var(--radius-md)', padding: '14px', cursor: 'pointer', transition: 'all 0.2s ease', minWidth: 0, boxSizing: 'border-box' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0, flex: 1 }}>
                      {ws.type.includes('Bar') ? <BarChart3 size={16} color="var(--primary)" style={{ flexShrink: 0 }} /> : ws.type.includes('Line') ? <LineChart size={16} color="var(--blue)" style={{ flexShrink: 0 }} /> : <TableIcon size={16} color="var(--yellow)" style={{ flexShrink: 0 }} />}
                      <span style={{ fontSize: '0.9375rem', fontWeight: 700, color: 'var(--ink)', overflowWrap: 'anywhere', wordBreak: 'break-word', minWidth: 0 }}>{ws.name}</span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
                      <span style={chartTypeBadge(ws.type)}>{ws.type}</span>
                      <ChevronRight size={14} color="var(--ink-3)" style={{ transform: isExpanded ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 0.2s ease', flexShrink: 0 }} />
                    </div>
                  </div>
                  {isExpanded && (
                    <div style={{ marginTop: '12px', paddingTop: '12px', borderTop: '1px solid var(--line)', display: 'flex', flexDirection: 'column', gap: '10px', minWidth: 0 }} onClick={(e) => e.stopPropagation()}>
                      <div>
                        <span style={specBlockLabel}>Axis &amp; Shelf Layout (Rows / Cols)</span>
                        <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginTop: '4px' }}>
                          {ws.columns.map((c, i) => <span key={`c-${i}`} className="tool-chip mono" style={{ color: 'var(--primary)', maxWidth: '100%', overflowWrap: 'anywhere' }}>Col: {c}</span>)}
                          {ws.rows.map((r, i) => <span key={`r-${i}`} className="tool-chip mono" style={{ color: 'var(--green)', maxWidth: '100%', overflowWrap: 'anywhere' }}>Row: {r}</span>)}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
        <div style={panelCard}>
          <div style={panelHeader}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
              <Calculator size={15} color="#9B51E0" style={{ flexShrink: 0 }} />
              <h3 style={{ fontSize: '0.875rem', fontWeight: 700, color: 'var(--ink)', margin: 0, whiteSpace: 'nowrap' }}>
                MSTR Derived Metrics
              </h3>
            </div>
            <span style={panelCountBadge}>{filteredCalcs.length}</span>
          </div>
          <div className="search-bar" style={{ marginBottom: '12px', width: '100%', boxSizing: 'border-box' }}>
            <Search size={14} className="search-icon" />
            <input type="text" className="input" placeholder="Search derived metrics..." value={calcSearch} onChange={(e) => setCalcSearch(e.target.value)} />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', maxHeight: '620px', overflowY: 'auto', paddingRight: '4px', minWidth: 0 }}>
            {filteredCalcs.map((cf) => {
              const isExpanded = expandedCalcs.has(cf.name);
              const isSelected = selectedCalc === cf.name;
              return (
                <div key={cf.name} onClick={() => toggleCalcExpand(cf.name)} style={{ background: isSelected ? 'rgba(155,81,224,0.08)' : 'var(--surface)', border: `1px solid ${isSelected ? '#9B51E0' : 'var(--line)'}`, borderRadius: 'var(--radius-md)', padding: '12px', cursor: 'pointer', transition: 'all 0.2s ease', minWidth: 0, boxSizing: 'border-box' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', minWidth: 0 }}>
                    <span style={{ fontSize: '0.875rem', fontWeight: 700, color: 'var(--ink)', overflowWrap: 'anywhere', wordBreak: 'break-word', minWidth: 0, flex: 1 }}>{cf.caption}</span>
                  </div>
                  {isExpanded && (
                    <div style={{ marginTop: '10px', paddingTop: '10px', borderTop: '1px solid var(--line)', display: 'flex', flexDirection: 'column', gap: '8px', minWidth: 0 }} onClick={(e) => e.stopPropagation()}>
                      <span style={specBlockLabel}>Compiled Formula</span>
                      <pre style={formulaBlock}>{cf.formula}</pre>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <div style={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 'var(--radius-lg)', padding: '20px', boxShadow: 'var(--shadow-card)', width: '100%', boxSizing: 'border-box', minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px', gap: '8px', flexWrap: 'wrap' }}>
          <div>
            <h3 style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--ink)', margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Database size={18} color="var(--blue)" style={{ flexShrink: 0 }} /> MicroStrategy Intelligent Cube Inspector
            </h3>
            <span style={{ fontSize: '0.75rem', color: 'var(--ink-3)' }}>Interactive entity schema synthesized from cube dataset</span>
          </div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 7fr) minmax(0, 3fr)', gap: '16px', width: '100%', boxSizing: 'border-box', minWidth: 0 }}>
          <div style={{ background: 'var(--field)', borderRadius: 'var(--radius-md)', padding: '16px 20px', border: '1px solid var(--line)', minHeight: '110px', display: 'flex', flexDirection: 'column', justifyContent: 'center', minWidth: 0, boxSizing: 'border-box' }}>
            <div style={{ fontSize: '0.6875rem', fontWeight: 700, textTransform: 'uppercase', color: 'var(--ink-3)', marginBottom: '10px' }}>Intelligent Cube Source</div>
            <div style={diagramNode}>
              <Database size={22} color="var(--primary)" style={{ flexShrink: 0 }} />
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: '0.9375rem', fontWeight: 700, color: 'var(--ink)', overflowWrap: 'anywhere' }}>{cubeName}</div>
                <div style={{ fontSize: '0.75rem', color: 'var(--ink-3)', marginTop: '2px' }}>MicroStrategy Cube Dataset</div>
              </div>
            </div>
          </div>
          <div style={{ background: 'var(--field)', borderRadius: 'var(--radius-md)', padding: '16px', border: '1px solid var(--line)', minWidth: 0, boxSizing: 'border-box', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '8px' }}>
              <div style={inspectorBox}>
                <span style={{ fontSize: '0.625rem', color: 'var(--ink-3)', fontWeight: 600 }}>Cube Attributes &amp; Measures</span>
                <span style={{ fontSize: '1.125rem', fontWeight: 700, color: 'var(--ink)' }}>{uniqueAttributes.length + baseMeasures.length}</span>
              </div>
              <div style={inspectorBox}>
                <span style={{ fontSize: '0.625rem', color: 'var(--ink-3)', fontWeight: 600 }}>Derived Metrics</span>
                <span style={{ fontSize: '1.125rem', fontWeight: 700, color: '#9B51E0' }}>{calcFields.length}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div style={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 'var(--radius-lg)', padding: '20px', boxShadow: 'var(--shadow-card)', marginTop: '20px', width: '100%', boxSizing: 'border-box', minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px', gap: '8px', flexWrap: 'wrap' }}>
          <div>
            <h3 style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--ink)', margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
              <FileSpreadsheet size={18} color="var(--primary)" style={{ flexShrink: 0 }} /> Data Model Sample Data Preview
            </h3>
            <span style={{ fontSize: '0.75rem', color: 'var(--ink-3)' }}>Sample records preview ({sampleDataRows.length} sample rows from {cubeName} dataset)</span>
          </div>
        </div>
        <div style={{ background: 'var(--field)', border: '1px solid var(--line)', borderRadius: 'var(--radius-md)', overflowX: 'auto', maxHeight: '420px' }}>
          <table className="log-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.78125rem' }}>
            <thead>
              <tr style={{ background: 'var(--surface-alt, rgba(0,0,0,0.12))', textAlign: 'left', position: 'sticky', top: 0, zIndex: 1 }}>
                {Object.keys(sampleDataRows[0]).map((key) => (
                  <th key={key} style={{ padding: '8px 10px', borderBottom: '1px solid var(--line)', color: 'var(--ink)', fontWeight: 700, whiteSpace: 'nowrap' }}>{key}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sampleDataRows.map((row, rIdx) => (
                <tr key={rIdx} style={{ borderBottom: '1px solid var(--line)' }}>
                  {Object.entries(row).map(([k, val], cIdx) => (
                    <td key={cIdx} style={{ padding: '8px 10px', whiteSpace: 'nowrap', color: k.includes('USD') ? 'var(--green, #22c55e)' : k.includes('ID') ? 'var(--primary)' : 'var(--ink)' }}>
                      {String(val)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

const kpiCard: React.CSSProperties = { padding: '14px 16px', background: 'var(--surface)', borderRadius: 'var(--radius-md)', border: '1px solid var(--line)', display: 'flex', flexDirection: 'column', gap: '4px', minWidth: 0, boxSizing: 'border-box' };
const statHeader: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: '6px', minWidth: 0 };
const kpiLabel: React.CSSProperties = { fontSize: '0.6875rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--ink-3)', whiteSpace: 'nowrap' };
const kpiValue: React.CSSProperties = { fontSize: '1.5rem', fontWeight: 700, color: 'var(--ink)' };
const panelCard: React.CSSProperties = { background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 'var(--radius-lg)', padding: '16px', boxShadow: 'var(--shadow-card)', minWidth: 0, width: '100%', boxSizing: 'border-box', overflow: 'hidden' };
const panelHeader: React.CSSProperties = { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px', gap: '8px' };
const panelCountBadge: React.CSSProperties = { fontSize: '0.75rem', fontWeight: 700, color: 'var(--primary)', background: 'var(--primary-tint)', padding: '2px 8px', borderRadius: 'var(--radius-full)', flexShrink: 0 };
const chartTypeBadge = (type: string): React.CSSProperties => ({ fontSize: '0.6875rem', fontWeight: 600, padding: '2px 8px', borderRadius: 'var(--radius-full)', background: type.includes('Bar') ? 'rgba(251,78,11,0.1)' : type.includes('Line') ? 'rgba(13,110,253,0.1)' : 'rgba(224,168,0,0.1)', color: type.includes('Bar') ? 'var(--primary)' : type.includes('Line') ? 'var(--blue)' : 'var(--yellow)', flexShrink: 0, whiteSpace: 'nowrap' });
const specBlockLabel: React.CSSProperties = { fontSize: '0.6875rem', fontWeight: 700, textTransform: 'uppercase', color: 'var(--ink-3)', display: 'block' };
const formulaBlock: React.CSSProperties = { padding: '8px 10px', background: 'var(--field)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--line)', fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: '#9B51E0', margin: '4px 0 0 0', whiteSpace: 'pre-wrap', wordBreak: 'break-word', overflowWrap: 'anywhere', overflowX: 'auto', maxWidth: '100%', boxSizing: 'border-box' };
const diagramNode: React.CSSProperties = { padding: '12px 16px', background: 'var(--field)', border: '1px solid var(--line)', borderRadius: 'var(--radius-md)', display: 'flex', alignItems: 'center', gap: '10px', maxWidth: '100%', boxSizing: 'border-box', minWidth: 0 };
const inspectorBox: React.CSSProperties = { padding: '8px', background: 'var(--field)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--line)', display: 'flex', flexDirection: 'column', gap: '2px', textAlign: 'center' };
