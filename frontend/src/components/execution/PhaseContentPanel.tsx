import React, { useState } from 'react';
import {
  getPhaseConfig,
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
  stageStatuses: _stageStatuses,
}) => {
  const phase = getPhaseConfig(phaseId);
  const [activeTab, setActiveTab] = useState(phase?.subViews[0]?.key || '');

  if (!phase) return null;

  const currentTabKey = phase.subViews.some(sv => sv.key === activeTab) ? activeTab : (phase.subViews[0]?.key || '');
  const ActiveSubView = SUB_VIEW_MAP[currentTabKey];

  return (
    <div className="phase-content-panel">
      {/* Sub-View Tabs (hidden if only 1 subview) */}
      {phase.subViews.length > 1 && (
        <div className="phase-tabs" style={{ marginTop: 0 }}>
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

      {/* Sub-View Content */}
      <div className="phase-tab-content">
        {ActiveSubView && <ActiveSubView />}
      </div>
    </div>
  );
};

export default PhaseContentPanel;
