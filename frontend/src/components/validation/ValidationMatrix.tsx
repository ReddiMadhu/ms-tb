import React from 'react';
import {
  Database,
  Table,
  Calculator,
  Filter,
  LayoutDashboard,
  Layers,
  FileCheck2,
  CheckCircle2,
  AlertTriangle,
  XCircle,
} from 'lucide-react';

import type { ValidationCheck } from '../../api';

export interface MatrixCategoryItem {
  id: string;
  name: string;
  score: number; // 0.0 to 1.0
  totalChecks: number;
  passedChecks: number;
  warningChecks: number;
  failedChecks: number;
  icon: string;
}

interface ValidationMatrixProps {
  categories?: MatrixCategoryItem[];
  checks?: ValidationCheck[];
  selectedCategoryId?: string;
  onSelectCategory?: (categoryId: string) => void;
}

const CATEGORY_NAMES: Record<string, { name: string; icon: string }> = {
  structural: { name: 'Structural Schema & Hierarchy', icon: 'Layers' },
  financial_kpi: { name: 'Financial & KPI Numeric Parity', icon: 'FileCheck2' },
  security: { name: 'Security & RLS Filters', icon: 'Filter' },
  visual: { name: 'Visual Charts & Layouts', icon: 'LayoutDashboard' },
  schema: { name: 'Schema & Column Parity', icon: 'Table' },
  calculation: { name: 'Calculations & LOD Fields', icon: 'Calculator' },
  datasource: { name: 'Datasource & Tables', icon: 'Database' },
};

const ICON_MAP: Record<string, React.ComponentType<{ size?: number }>> = {
  Database,
  Table,
  Calculator,
  Filter,
  LayoutDashboard,
  Layers,
  FileCheck2,
};

export const ValidationMatrix: React.FC<ValidationMatrixProps> = ({
  categories: customCategories,
  checks = [],
  selectedCategoryId,
  onSelectCategory,
}) => {
  // Derive categories dynamically from ground-truth checks if not explicitly provided
  let categories: MatrixCategoryItem[] = [];

  if (customCategories && customCategories.length > 0) {
    categories = customCategories;
  } else if (checks.length > 0) {
    const grouped: Record<string, { total: number; passed: number; failed: number }> = {};
    for (const c of checks) {
      const cat = c.category || 'structural';
      if (!grouped[cat]) grouped[cat] = { total: 0, passed: 0, failed: 0 };
      grouped[cat].total += 1;
      if (c.passed) {
        grouped[cat].passed += 1;
      } else {
        grouped[cat].failed += 1;
      }
    }

    categories = Object.entries(grouped).map(([catKey, counts]) => {
      const info = CATEGORY_NAMES[catKey] || {
        name: catKey.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase()),
        icon: 'FileCheck2',
      };
      return {
        id: catKey,
        name: info.name,
        score: counts.total > 0 ? counts.passed / counts.total : 1.0,
        totalChecks: counts.total,
        passedChecks: counts.passed,
        warningChecks: 0,
        failedChecks: counts.failed,
        icon: info.icon,
      };
    });
  }

  if (categories.length === 0) {
    return (
      <div
        style={{
          padding: '24px',
          textAlign: 'center',
          background: 'var(--field)',
          borderRadius: 'var(--radius-md)',
          color: 'var(--ink-3)',
          fontSize: '0.875rem',
          marginBottom: '20px',
        }}
      >
        No category validation sweeps executed yet.
      </div>
    );
  }
  return (
    <div className="validation-matrix-grid">
      {categories.map((cat) => {
        const isSelected = selectedCategoryId === cat.id;
        const IconComponent = ICON_MAP[cat.icon] || FileCheck2;
        const percent = (cat.score * 100).toFixed(1);
        const isPerfect = cat.score >= 0.99;
        const isWarning = cat.score < 0.99 && cat.score >= 0.9;

        const pillBg = isPerfect
          ? 'var(--green-tint)'
          : isWarning
          ? 'var(--yellow-tint)'
          : 'var(--red-tint)';
        const pillColor = isPerfect
          ? 'var(--green)'
          : isWarning
          ? 'var(--yellow)'
          : 'var(--red)';

        return (
          <div
            key={cat.id}
            className={`matrix-card ${isSelected ? 'selected' : ''}`}
            onClick={() => onSelectCategory?.(cat.id)}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <div
                style={{
                  width: '36px',
                  height: '36px',
                  borderRadius: 'var(--radius-sm)',
                  background: 'var(--field)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: 'var(--ink-2)',
                }}
              >
                <IconComponent size={18} />
              </div>
              <div>
                <div style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--ink)' }}>
                  {cat.name}
                </div>
                <div style={{ fontSize: '0.75rem', color: 'var(--ink-3)', marginTop: '2px' }}>
                  {cat.passedChecks} of {cat.totalChecks} checks verified
                </div>
              </div>
            </div>

            <div
              className="matrix-score-pill"
              style={{ backgroundColor: pillBg, color: pillColor }}
            >
              {percent}%
            </div>
          </div>
        );
      })}
    </div>
  );
};

export default ValidationMatrix;
