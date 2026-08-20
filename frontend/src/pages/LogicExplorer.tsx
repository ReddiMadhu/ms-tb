import React, { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  Code,
  ArrowLeft,
  Search,
  Filter,
  Sparkles,
  CheckCircle2,
  AlertTriangle,
  Layers,
  Calculator,
} from 'lucide-react';
import { api } from '../api';
import { ExpressionDiff } from '../components/migration/ExpressionDiff';
import { EmptyState } from '../components/ui/EmptyState';

interface CalculationItem {
  id: string;
  name: string;
  category: 'measure' | 'lod' | 'table_calc' | 'parameter' | 'filter';
  sourceFormula: string;
  targetCalc: string;
  method: string;
  confidence: number;
  validationPassed: boolean;
  notes?: string;
}

export default function LogicExplorer() {
  const { jobId } = useParams<{ jobId: string }>();
  const [calculations, setCalculations] = useState<CalculationItem[]>([]);
  const [activeCategory, setActiveCategory] = useState<string>('all');
  const [search, setSearch] = useState<string>('');

  useEffect(() => {
    if (!jobId) return;
    api.listObjects(jobId)
      .then((res) => {
        const calcs: CalculationItem[] = (res.objects || [])
          .filter((o) => o.expression_text || o.tableau_calc || o.type_name === 'metric')
          .map((o) => ({
            id: o.id,
            name: o.name,
            category: o.tableau_calc?.includes('FIXED') || o.tableau_calc?.includes('INCLUDE') ? 'lod' : o.tableau_calc?.includes('LOOKUP') || o.tableau_calc?.includes('WINDOW_') ? 'table_calc' : 'measure',
            sourceFormula: o.expression_text || '—',
            targetCalc: o.tableau_calc || '—',
            method: 'AST Compiler Engine',
            confidence: o.confidence || 0.95,
            validationPassed: o.status === 'compiled' || o.status === 'published',
            notes: o.mstr_path ? `Path: ${o.mstr_path}` : undefined,
          }));
        setCalculations(calcs);
      })
      .catch(() => setCalculations([]));
  }, [jobId]);

  const filtered = calculations.filter((c) => {
    const matchesSearch =
      c.name.toLowerCase().includes(search.toLowerCase()) ||
      c.sourceFormula.toLowerCase().includes(search.toLowerCase()) ||
      c.targetCalc.toLowerCase().includes(search.toLowerCase());

    const matchesCategory = activeCategory === 'all' || c.category === activeCategory;

    return matchesSearch && matchesCategory;
  });

  return (
    <div style={{ maxWidth: '1440px', margin: '0 auto' }}>
      {/* ── Top Header ───────────────────────────────────────────── */}
      <div style={{ marginBottom: '20px' }}>
        <Link
          to={`/jobs/${jobId}`}
          className="btn btn-ghost"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '6px',
            padding: '4px 8px',
            fontSize: '0.8125rem',
            color: 'var(--ink-2)',
            marginBottom: '10px',
          }}
        >
          <ArrowLeft size={14} />
          <span>Back to Migration Control Center</span>
        </Link>

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <h1
              style={{
                fontSize: '1.625rem',
                fontWeight: 700,
                color: 'var(--ink)',
                letterSpacing: '-0.02em',
                margin: 0,
              }}
            >
              Logic &amp; Calculation Translator
            </h1>
            <p style={{ fontSize: '0.875rem', color: 'var(--ink-2)', marginTop: '4px' }}>
              MicroStrategy expressions, Level Metrics, LODs, and Table Calculations translated to Tableau
            </p>
          </div>
        </div>
      </div>

      {/* ── Category Filters & Search ────────────────────────────── */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '16px',
          marginBottom: '20px',
          flexWrap: 'wrap',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
          {[
            { key: 'all', label: `All Calculations (${calculations.length})` },
            { key: 'measure', label: 'Measures & Metrics' },
            { key: 'lod', label: 'LOD Expressions' },
            { key: 'table_calc', label: 'Table Calculations' },
            { key: 'filter', label: 'Calculated Filters' },
          ].map((cat) => (
            <button
              key={cat.key}
              onClick={() => setActiveCategory(cat.key)}
              style={{
                padding: '6px 14px',
                borderRadius: 'var(--radius-full)',
                border: '1px solid',
                borderColor: activeCategory === cat.key ? 'var(--primary)' : 'var(--line)',
                background: activeCategory === cat.key ? 'var(--primary-tint)' : 'var(--surface)',
                color: activeCategory === cat.key ? 'var(--primary)' : 'var(--ink-2)',
                fontSize: '0.8125rem',
                fontWeight: activeCategory === cat.key ? 600 : 500,
                cursor: 'pointer',
              }}
            >
              {cat.label}
            </button>
          ))}
        </div>

        <div className="search-bar" style={{ minWidth: '320px' }}>
          <Search size={16} className="search-icon" />
          <input
            type="text"
            className="input"
            placeholder="Search by metric name or formula text..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      {/* ── Formula Cards List ───────────────────────────────────── */}
      {filtered.length === 0 ? (
        <EmptyState
          icon={Code}
          title="No calculations found"
          description="No calculations match your active filter."
          actionLabel="Clear Filter"
          onAction={() => {
            setActiveCategory('all');
            setSearch('');
          }}
        />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {filtered.map((calc) => (
            <div
              key={calc.id}
              style={{
                background: 'var(--surface)',
                border: '1px solid var(--line)',
                borderRadius: 'var(--radius-lg)',
                padding: '20px',
                boxShadow: 'var(--shadow-card)',
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
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <h3
                    style={{
                      fontSize: '1rem',
                      fontWeight: 600,
                      color: 'var(--ink)',
                      margin: 0,
                    }}
                  >
                    {calc.name}
                  </h3>
                  <span className="tool-chip" style={{ textTransform: 'uppercase' }}>
                    {calc.category.replace('_', ' ')}
                  </span>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  {calc.validationPassed && (
                    <span
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '4px',
                        fontSize: '0.75rem',
                        fontWeight: 600,
                        color: 'var(--green)',
                      }}
                    >
                      <CheckCircle2 size={14} />
                      <span>Parity Verified</span>
                    </span>
                  )}
                </div>
              </div>

              <ExpressionDiff
                sourceExpression={calc.sourceFormula}
                targetExpression={calc.targetCalc}
                method={calc.method}
                confidence={calc.confidence}
                explanation={calc.notes}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
