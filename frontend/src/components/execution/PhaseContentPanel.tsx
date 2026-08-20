import React, { useState } from 'react';
import {
  Search,
  Layers,
  FileSpreadsheet,
  ShieldCheck,
  Check,
  Loader2,
  AlertTriangle,
  XCircle,
} from 'lucide-react';
import {
  getPhaseConfig,
  getPhaseStatus,
  PIPELINE_STAGES,
  type PhaseConfig,
} from '../../config/pipeline.config';
import type { StageStatus } from '../../config/status.config';

// Direct imports — these are already statically imported by App.tsx routes
import Objects from '../../pages/Objects';
import LineageExplorer from '../../pages/LineageExplorer';
import SemanticModel from '../../pages/SemanticModel';
import LogicExplorer from '../../pages/LogicExplorer';
import DashboardInventory from '../../pages/DashboardInventory';
import ExportCenter from '../../pages/ExportCenter';
import Validation from '../../pages/Validation';
import ReviewQueue from '../../pages/ReviewQueue';
import MigrationReport from '../../pages/MigrationReport';

const PHASE_ICON_MAP: Record<string, React.ComponentType<{ size?: number; className?: string }>> = {
  Search,
  Layers,
  FileSpreadsheet,
  ShieldCheck,
};

const SUB_VIEW_MAP: Record<string, React.ComponentType<any>> = {
  objects: Objects,
  lineage: LineageExplorer,
  semantic: SemanticModel,
  logic: LogicExplorer,
  dashboards: DashboardInventory,
  exports: ExportCenter,
  validation: Validation,
  review: ReviewQueue,
  report: MigrationReport,
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
  if (!phase) return null;

  const [activeTab, setActiveTab] = useState(phase.subViews[0]?.key || '');
  const phaseStatus = getPhaseStatus(phaseId, stageStatuses);
  const IconComponent = PHASE_ICON_MAP[phase.icon] || Search;

  // Get child stage info
  const childStages = phase.stageIds.map(sid => {
    const stageCfg = PIPELINE_STAGES.find(s => s.id === sid);
    const status = stageStatuses[sid] || 'WAITING';
    return { id: sid, title: stageCfg?.shortTitle || sid, status };
  });

  const StatusIcon = ({ status }: { status: string }) => {
    switch (status) {
      case 'COMPLETED': return <Check size={12} strokeWidth={3} />;
      case 'RUNNING': return <Loader2 size={12} className="spin-icon" />;
      case 'FAILED': return <XCircle size={12} />;
      case 'WARNING': return <AlertTriangle size={12} />;
      default: return <div className="phase-stage-dot" />;
    }
  };

  const ActiveSubView = SUB_VIEW_MAP[activeTab];

  return (
    <div className="phase-content-panel">
      {/* Phase Header */}
      <div className="phase-content-header" style={{ borderLeftColor: phase.color }}>
        <div className="phase-content-title-row">
          <div className="phase-content-icon" style={{ background: phase.color, color: '#fff' }}>
            <IconComponent size={18} />
          </div>
          <div>
            <h3 className="phase-content-title">
              Phase {phase.number}: {phase.title}
            </h3>
            <p className="phase-content-desc">{phase.description}</p>
          </div>
          <span className={`phase-status-badge ${phaseStatus.toLowerCase()}`}>
            <StatusIcon status={phaseStatus} />
            <span>{phaseStatus === 'RUNNING' ? 'In Progress' : phaseStatus.charAt(0) + phaseStatus.slice(1).toLowerCase()}</span>
          </span>
        </div>

        {/* Child stage pills */}
        <div className="phase-stage-pills">
          {childStages.map(cs => (
            <span
              key={cs.id}
              className={`phase-stage-pill ${cs.status.toLowerCase()}`}
              title={`${cs.title}: ${cs.status}`}
            >
              <StatusIcon status={cs.status} />
              <span>{cs.title}</span>
            </span>
          ))}
        </div>
      </div>

      {/* Sub-View Tabs */}
      <div className="phase-tabs">
        {phase.subViews.map(sv => (
          <button
            key={sv.key}
            type="button"
            className={`phase-tab ${activeTab === sv.key ? 'active' : ''}`}
            onClick={() => setActiveTab(sv.key)}
          >
            {sv.label}
          </button>
        ))}
      </div>

      {/* Sub-View Content */}
      <div className="phase-tab-content">
        {ActiveSubView && <ActiveSubView />}
      </div>
    </div>
  );
};

export default PhaseContentPanel;
