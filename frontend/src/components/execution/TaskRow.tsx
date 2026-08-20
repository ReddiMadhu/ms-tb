import React, { useState } from 'react';
import {
  CheckCircle2,
  Loader2,
  AlertTriangle,
  XCircle,
  Clock,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import type { StageStatus } from '../../config/status.config';

export interface TaskRowData {
  id: string;
  name: string;
  detail?: string;
  status: StageStatus;
  durationMs?: number;
  processedCount?: number;
  totalCount?: number;
  logs?: string[];
}

interface TaskRowProps {
  task: TaskRowData;
  initiallyExpanded?: boolean;
}

export const TaskRow: React.FC<TaskRowProps> = ({ task, initiallyExpanded = false }) => {
  const [expanded, setExpanded] = useState(initiallyExpanded);

  const getStatusIcon = (status: StageStatus) => {
    switch (status) {
      case 'COMPLETED':
        return <CheckCircle2 size={18} color="var(--green)" />;
      case 'RUNNING':
        return <Loader2 size={18} color="var(--blue)" className="spin-icon" />;
      case 'WARNING':
        return <AlertTriangle size={18} color="var(--yellow)" />;
      case 'FAILED':
        return <XCircle size={18} color="var(--red)" />;
      case 'WAITING':
      default:
        return <Clock size={18} color="var(--ink-3)" />;
    }
  };

  const formatDuration = (ms?: number) => {
    if (!ms) return null;
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  };

  const hasLogs = task.logs && task.logs.length > 0;

  return (
    <div
      style={{
        background: 'var(--surface)',
        border: '1px solid var(--line)',
        borderRadius: 'var(--radius-md)',
        overflow: 'hidden',
        boxShadow: 'var(--shadow-card)',
      }}
    >
      <div
        className="task-row"
        onClick={() => hasLogs && setExpanded(!expanded)}
        style={{
          cursor: hasLogs ? 'pointer' : 'default',
          border: 'none',
          borderRadius: 0,
          boxShadow: 'none',
        }}
      >
        <div className="task-row-left">
          {getStatusIcon(task.status)}
          <div>
            <div className="task-row-title">{task.name}</div>
            {task.detail && <div className="task-row-detail">{task.detail}</div>}
          </div>
        </div>

        <div className="task-row-right">
          {task.processedCount !== undefined && task.totalCount !== undefined && (
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '0.75rem',
                color: 'var(--ink-2)',
                background: 'var(--field)',
                padding: '3px 8px',
                borderRadius: 'var(--radius-sm)',
              }}
            >
              {task.processedCount} / {task.totalCount}
            </span>
          )}
          {task.durationMs && (
            <span className="task-row-duration">{formatDuration(task.durationMs)}</span>
          )}
          {hasLogs && (
            <button
              type="button"
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--ink-3)',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                padding: '2px',
              }}
            >
              {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            </button>
          )}
        </div>
      </div>

      {expanded && hasLogs && (
        <div
          style={{
            padding: '12px 18px',
            background: 'var(--inset)',
            borderTop: '1px solid var(--line)',
            fontFamily: 'var(--font-mono)',
            fontSize: '0.75rem',
            color: 'var(--ink-2)',
            display: 'flex',
            flexDirection: 'column',
            gap: '4px',
          }}
        >
          {task.logs?.map((log, i) => (
            <div key={i} style={{ display: 'flex', gap: '8px' }}>
              <span style={{ color: 'var(--ink-3)' }}>&gt;</span>
              <span>{log}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default TaskRow;
