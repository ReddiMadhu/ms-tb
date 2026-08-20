import React from 'react';
import {
  Clock,
  Loader2,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  MinusCircle,
  CheckCheck,
  Ban,
  ArrowUpCircle,
  Info,
  OctagonX,
  Circle,
  SkipForward
} from 'lucide-react';
import { getJobStatus, getStageStatus, getSeverityConfig, type StatusConfig } from '../../config/status.config';

interface StatusBadgeProps {
  status: string;
  type?: 'job' | 'stage' | 'severity';
  size?: 'sm' | 'md' | 'lg';
  showIcon?: boolean;
  className?: string;
}

const ICON_MAP: Record<string, React.ComponentType<{ size?: number; className?: string }>> = {
  Clock,
  Loader2,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  MinusCircle,
  CheckCheck,
  Ban,
  ArrowUpCircle,
  Info,
  OctagonX,
  Circle,
  SkipForward,
};

export const StatusBadge: React.FC<StatusBadgeProps> = ({
  status,
  type = 'job',
  size = 'md',
  showIcon = true,
  className = '',
}) => {
  let config: StatusConfig;
  if (type === 'stage') {
    config = getStageStatus(status);
  } else if (type === 'severity') {
    config = getSeverityConfig(status);
  } else {
    config = getJobStatus(status);
  }

  const IconComponent = ICON_MAP[config.icon] || Circle;
  const isSpinning = config.icon === 'Loader2';
  const iconSize = size === 'sm' ? 12 : size === 'lg' ? 16 : 14;

  return (
    <span
      className={`status-badge ${size} ${className}`}
      style={{
        backgroundColor: config.tintVar,
        color: config.colorVar,
        borderColor: `color-mix(in srgb, ${config.colorVar} 25%, transparent)`,
      }}
      title={config.description}
    >
      {showIcon && (
        <IconComponent
          size={iconSize}
          className={isSpinning ? 'spin-icon' : undefined}
        />
      )}
      <span>{config.label}</span>
    </span>
  );
};

export default StatusBadge;
