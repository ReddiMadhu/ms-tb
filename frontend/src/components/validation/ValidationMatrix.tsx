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
  selectedCategoryId?: string;
  onSelectCategory?: (categoryId: string) => void;
}

const DEFAULT_CATEGORIES: MatrixCategoryItem[] = [
  {
    id: 'datasource',
    name: 'Datasource Mapping',
    score: 1.0,
    totalChecks: 12,
    passedChecks: 12,
    warningChecks: 0,
    failedChecks: 0,
    icon: 'Database',
  },
  {
    id: 'schema',
    name: 'Schema & Column Parity',
    score: 1.0,
    totalChecks: 48,
    passedChecks: 48,
    warningChecks: 0,
    failedChecks: 0,
    icon: 'Table',
  },
  {
    id: 'calculation',
    name: 'Calculation & LOD Mapping',
    score: 0.987,
    totalChecks: 183,
    passedChecks: 180,
    warningChecks: 3,
    failedChecks: 0,
    icon: 'Calculator',
  },
  {
    id: 'filter',
    name: 'Filter & Prompt Parity',
    score: 0.974,
    totalChecks: 38,
    passedChecks: 37,
    warningChecks: 1,
    failedChecks: 0,
    icon: 'Filter',
  },
  {
    id: 'visual',
    name: 'Visual Chart Conversion',
    score: 0.962,
    totalChecks: 52,
    passedChecks: 50,
    warningChecks: 2,
    failedChecks: 0,
    icon: 'LayoutDashboard',
  },
  {
    id: 'layout',
    name: 'Dashboard Layout Grid',
    score: 0.991,
    totalChecks: 24,
    passedChecks: 24,
    warningChecks: 0,
    failedChecks: 0,
    icon: 'Layers',
  },
  {
    id: 'numeric',
    name: 'Numerical Value Parity',
    score: 0.998,
    totalChecks: 1240,
    passedChecks: 1238,
    warningChecks: 2,
    failedChecks: 0,
    icon: 'FileCheck2',
  },
];

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
  categories = DEFAULT_CATEGORIES,
  selectedCategoryId,
  onSelectCategory,
}) => {
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
