import React, { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  ArrowLeft,
  Layers,
  Code,
  ShieldCheck,
  GitBranch,
  ExternalLink,
  Sparkles,
  FileSpreadsheet,
  Database,
  CheckCircle2,
} from 'lucide-react';
import { api, type MigrationObject } from '../api';
import { StatusBadge } from '../components/ui/StatusBadge';
import { ExpressionDiff } from '../components/migration/ExpressionDiff';

export default function ObjectDetail() {
  const { jobId, objId } = useParams<{ jobId: string; objId: string }>();
  const [object, setObject] = useState<MigrationObject | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!jobId || !objId) return;
    api.getObject(jobId, objId)
      .then((data) => {
        setObject(data);
        setLoading(false);
      })
      .catch(() => {
        setObject(null);
        setLoading(false);
      });
  }, [jobId, objId]);

  if (!object) return null;

  return (
    <div style={{ maxWidth: '1440px', margin: '0 auto' }}>
      {/* ── Breadcrumb & Header ──────────────────────────────────── */}
      <div style={{ marginBottom: '20px' }}>
        <Link
          to={`/jobs/${jobId}/objects`}
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
          <span>Back to Object Catalog</span>
        </Link>

        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <h1
                style={{
                  fontSize: '1.625rem',
                  fontWeight: 700,
                  color: 'var(--ink)',
                  letterSpacing: '-0.02em',
                  margin: 0,
                }}
              >
                {object.name}
              </h1>
              <StatusBadge status={object.status} size="md" />
              <span className="tool-chip" style={{ textTransform: 'capitalize' }}>
                {object.type_name}
              </span>
            </div>

            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
                marginTop: '6px',
                fontSize: '0.8125rem',
                color: 'var(--ink-2)',
              }}
            >
              <span>Path: {object.mstr_path || '/Public Objects/'}</span>
              <span>&bull;</span>
              <span className="mono" style={{ color: 'var(--ink-3)' }}>
                MSTR GUID: {object.mstr_id}
              </span>
            </div>
          </div>

          <div
            style={{
              padding: '8px 16px',
              borderRadius: 'var(--radius-md)',
              background: object.confidence && object.confidence >= 0.9 ? 'var(--green-tint)' : 'var(--blue-tint)',
              color: object.confidence && object.confidence >= 0.9 ? 'var(--green)' : 'var(--blue)',
              fontWeight: 700,
              fontSize: '1rem',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
            }}
          >
            <CheckCircle2 size={18} />
            <span>{object.confidence !== undefined && object.confidence !== null ? `${Math.round(object.confidence * 100)}% Confidence` : 'Cataloged'}</span>
          </div>
        </div>
      </div>

      {/* ── Side-by-Side Formula Diff ────────────────────────────── */}
      {(object.expression_text || object.tableau_calc) && (
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
          <h3 style={{ fontSize: '1.0625rem', fontWeight: 600, color: 'var(--ink)', margin: 0 }}>
            Expression Translation &amp; Formula Comparison
          </h3>
          <p style={{ fontSize: '0.8125rem', color: 'var(--ink-2)', marginTop: '4px' }}>
            {object.translation_method ? `Translation Method: ${object.translation_method}` : 'Universal BI-IR mapping from MicroStrategy expression to Tableau calculated field dialect'}
          </p>

          <ExpressionDiff
            sourceExpression={object.expression_text || '—'}
            targetExpression={object.tableau_calc || '—'}
            confidence={object.confidence}
            explanation={object.translation_method ? `Translated via ${object.translation_method}` : 'Extracted formula definition from MicroStrategy metadata.'}
          />
        </div>
      )}

      {/* ── Dependency & Blast Radius Hierarchy ─────────────────── */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: '20px',
          marginBottom: '24px',
        }}
      >
        <div
          style={{
            background: 'var(--surface)',
            border: '1px solid var(--line)',
            borderRadius: 'var(--radius-lg)',
            padding: '20px',
            boxShadow: 'var(--shadow-card)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
            <GitBranch size={18} color="var(--primary)" />
            <h3 style={{ fontSize: '0.9375rem', fontWeight: 600, color: 'var(--ink)', margin: 0 }}>
              Upstream Inputs &amp; Dependencies
            </h3>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {((object as any).dependency_ids || object.dependencies)?.length ? (
              ((object as any).dependency_ids || object.dependencies).map((dep: string, i: number) => (
                <div
                  key={i}
                  style={{
                    padding: '8px 12px',
                    background: 'var(--field)',
                    borderRadius: 'var(--radius-sm)',
                    fontSize: '0.8125rem',
                    fontFamily: 'var(--font-mono)',
                    color: 'var(--ink)',
                  }}
                >
                  {dep}
                </div>
              ))
            ) : (
              <span style={{ fontSize: '0.8125rem', color: 'var(--ink-3)' }}>
                Base entity with direct warehouse relation.
              </span>
            )}
          </div>
        </div>

        <div
          style={{
            background: 'var(--surface)',
            border: '1px solid var(--line)',
            borderRadius: 'var(--radius-lg)',
            padding: '20px',
            boxShadow: 'var(--shadow-card)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
            <Layers size={18} color="var(--blue)" />
            <h3 style={{ fontSize: '0.9375rem', fontWeight: 600, color: 'var(--ink)', margin: 0 }}>
              Downstream Dependent Worksheets &amp; Dossiers
            </h3>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {object.dependents?.length ? (
              object.dependents.map((dep, i) => (
                <div
                  key={i}
                  style={{
                    padding: '8px 12px',
                    background: 'var(--field)',
                    borderRadius: 'var(--radius-sm)',
                    fontSize: '0.8125rem',
                    color: 'var(--ink)',
                  }}
                >
                  {dep}
                </div>
              ))
            ) : (
              <span style={{ fontSize: '0.8125rem', color: 'var(--ink-3)' }}>
                No active downstream dependents.
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
