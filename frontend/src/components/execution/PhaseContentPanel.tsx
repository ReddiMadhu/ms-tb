import React, { useState } from 'react';
import { Loader2 } from 'lucide-react';
import {
  getPhaseConfig,
  getPhaseStatus,
  type PhaseConfig,
} from '../../config/pipeline.config';

// Direct imports — these are already statically imported by App.tsx routes
import Objects from '../../pages/Objects';
import LogicExplorer from '../../pages/LogicExplorer';
import DashboardInventory from '../../pages/DashboardInventory';
import ExportCenter from '../../pages/ExportCenter';

const SUB_VIEW_MAP: Record<string, React.ComponentType<any>> = {
  objects: Objects,
  logic: LogicExplorer,
  dashboards: DashboardInventory,
  exports: ExportCenter,
};

interface PhaseContentPanelProps {
  phaseId: string;
  stageStatuses: Record<string, string>;
}

export const PhaseContentPanel: React.FC<PhaseContentPanelProps> = ({
  phaseId,
  stageStatuses,
}) => {
  const phase = getPhaseConfig(phaseId);
  const [activeTab, setActiveTab] = useState(phase?.subViews[0]?.key || '');

  if (!phase) return null;

  const status = getPhaseStatus(phaseId, stageStatuses);
  const isPhaseLoading = status === 'RUNNING' || status === 'WAITING';

  const currentTabKey = phase.subViews.some(sv => sv.key === activeTab) ? activeTab : (phase.subViews[0]?.key || '');
  const ActiveSubView = SUB_VIEW_MAP[currentTabKey];

  return (
    <div style={{ background: 'transparent', border: 'none', boxShadow: 'none', margin: 0, padding: 0 }}>
      {/* Sub-View Tabs (hidden if only 1 subview or if phase is currently loading) */}
      {!isPhaseLoading && phase.subViews.length > 1 && (
        <div className="phase-tabs" style={{ marginTop: 0, marginBottom: '16px' }}>
          {phase.subViews.map(sv => (
            <button
              key={sv.key}
              type="button"
              className={`phase-tab ${currentTabKey === sv.key ? 'active' : ''}`}
              onClick={() => setActiveTab(sv.key)}
            >
              {sv.label}
            </button>
          ))}
        </div>
      )}

      {/* Sub-View Content — rendered directly with no extra container padding/margin/background */}
      {isPhaseLoading ? (
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            minHeight: '320px',
            gap: '16px',
            color: 'var(--ink-2)',
            background: 'var(--surface)',
            border: '1px solid var(--line)',
            borderRadius: 'var(--radius-lg)',
            padding: '40px 20px',
          }}
        >
          <Loader2 size={36} className="spin-icon" style={{ color: 'var(--primary, #6366f1)' }} />
          <span style={{ fontSize: '0.9375rem', fontWeight: 500 }}>
            Loading data for this phase...
          </span>
        </div>
      ) : (
        ActiveSubView && <ActiveSubView />
      )}
    </div>
  );
};

export default PhaseContentPanel;
