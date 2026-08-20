import React from 'react';
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
  PIPELINE_PHASES,
  type PhaseConfig,
  getPhaseStatus,
} from '../../config/pipeline.config';

interface PipelineStepperProps {
  selectedPhaseId?: string;
  onSelectPhase?: (phaseId: string) => void;
  stageStatuses: Record<string, string>;
}

const PHASE_ICON_MAP: Record<string, React.ComponentType<{ size?: number; className?: string }>> = {
  Search,
  Layers,
  FileSpreadsheet,
  ShieldCheck,
};

export const PipelineStepper: React.FC<PipelineStepperProps> = ({
  selectedPhaseId,
  onSelectPhase,
  stageStatuses,
}) => {
  return (
    <div className="pipeline-stepper-container">
      <div className="pipeline-stepper">
        {PIPELINE_PHASES.map((phase, idx) => {
          const status = getPhaseStatus(phase.id, stageStatuses);
          const isSelected = selectedPhaseId === phase.id;
          const isLast = idx === PIPELINE_PHASES.length - 1;
          const IconComponent = PHASE_ICON_MAP[phase.icon] || Search;

          return (
            <React.Fragment key={phase.id}>
              <button
                type="button"
                className={`pipeline-step-node ${status.toLowerCase()} ${
                  isSelected ? 'active' : ''
                }`}
                onClick={() => onSelectPhase?.(phase.id)}
                title={`${phase.title} — ${phase.description}`}
              >
                <div className="pipeline-step-circle" style={{ '--phase-color': phase.color } as React.CSSProperties}>
                  {status === 'COMPLETED' ? (
                    <Check size={20} strokeWidth={2.5} />
                  ) : status === 'RUNNING' ? (
                    <Loader2 size={20} className="spin-icon" />
                  ) : status === 'FAILED' ? (
                    <XCircle size={20} />
                  ) : status === 'WARNING' ? (
                    <AlertTriangle size={20} />
                  ) : (
                    <IconComponent size={20} />
                  )}
                </div>
                <span className="pipeline-step-label">{phase.title}</span>
                <span className="pipeline-step-sub">{phase.stageIds.length} stages</span>
              </button>

              {!isLast && (
                <div
                  className={`pipeline-connector ${
                    status === 'COMPLETED'
                      ? 'completed'
                      : status === 'RUNNING'
                      ? 'running'
                      : ''
                  }`}
                />
              )}
            </React.Fragment>
          );
        })}
      </div>
    </div>
  );
};

export default PipelineStepper;
