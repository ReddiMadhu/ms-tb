import React from 'react';
import {
  Search,
  GitBranch,
  Layers,
  Copy,
  Code,
  Sparkles,
  LayoutDashboard,
  Database,
  FileOutput,
  FileSpreadsheet,
  ShieldCheck,
  FileText,
  Check,
  Loader2,
  AlertTriangle,
  XCircle,
} from 'lucide-react';
import { PIPELINE_STAGES, type PipelineStageConfig } from '../../config/pipeline.config';
import type { StageStatus } from '../../config/status.config';

interface PipelineStepperProps {
  currentStageId?: string;
  selectedStageId?: string;
  onSelectStage?: (stageId: string) => void;
  stagesCompleted?: string[];
  failedStageId?: string;
  warningStageIds?: string[];
}

const ICON_MAP: Record<string, React.ComponentType<{ size?: number; className?: string }>> = {
  Search,
  GitBranch,
  Layers,
  Copy,
  Code,
  Sparkles,
  LayoutDashboard,
  Database,
  FileOutput,
  FileSpreadsheet,
  ShieldCheck,
  FileText,
};

export const PipelineStepper: React.FC<PipelineStepperProps> = ({
  currentStageId,
  selectedStageId,
  onSelectStage,
  stagesCompleted = [],
  failedStageId,
  warningStageIds = [],
}) => {
  const getStageState = (stage: PipelineStageConfig): StageStatus => {
    if (failedStageId === stage.id) return 'FAILED';
    if (warningStageIds.includes(stage.id)) return 'WARNING';
    if (stagesCompleted.includes(stage.id)) return 'COMPLETED';
    if (currentStageId === stage.id) return 'RUNNING';
    return 'WAITING';
  };

  return (
    <div className="pipeline-stepper-container">
      <div className="pipeline-stepper">
        {PIPELINE_STAGES.map((stage, idx) => {
          const state = getStageState(stage);
          const isSelected = selectedStageId === stage.id;
          const isLast = idx === PIPELINE_STAGES.length - 1;
          const IconComponent = ICON_MAP[stage.icon] || Code;

          return (
            <React.Fragment key={stage.id}>
              <button
                type="button"
                className={`pipeline-step-node ${state.toLowerCase()} ${
                  isSelected ? 'active' : ''
                }`}
                onClick={() => onSelectStage?.(stage.id)}
                title={`${stage.title} — ${stage.description}`}
              >
                <div className="pipeline-step-circle">
                  {state === 'COMPLETED' ? (
                    <Check size={18} strokeWidth={2.5} />
                  ) : state === 'RUNNING' ? (
                    <Loader2 size={18} className="spin-icon" />
                  ) : state === 'FAILED' ? (
                    <XCircle size={18} />
                  ) : state === 'WARNING' ? (
                    <AlertTriangle size={18} />
                  ) : (
                    <IconComponent size={16} />
                  )}
                </div>
                <span className="pipeline-step-label">{stage.shortTitle}</span>
              </button>

              {!isLast && (
                <div
                  className={`pipeline-connector ${
                    state === 'COMPLETED'
                      ? 'completed'
                      : state === 'RUNNING'
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
