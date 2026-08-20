import React from 'react';
import { Clock, Loader2, CheckCircle2 } from 'lucide-react';

interface MigrationProgressProps {
  progressPercent: number;
  currentStageName?: string;
  elapsedSeconds?: number;
  isRunning?: boolean;
  isComplete?: boolean;
}

export const MigrationProgress: React.FC<MigrationProgressProps> = ({
  progressPercent,
  currentStageName,
  elapsedSeconds,
  isRunning = false,
  isComplete = false,
}) => {
  const normalized = Math.min(100, Math.max(0, Math.round(progressPercent)));

  const formatElapsed = (sec: number) => {
    const mins = Math.floor(sec / 60);
    const s = sec % 60;
    return `${mins}m ${s.toString().padStart(2, '0')}s`;
  };

  return (
    <div
      style={{
        background: 'var(--surface)',
        border: '1px solid var(--line)',
        borderRadius: 'var(--radius-lg)',
        padding: '16px 20px',
        marginBottom: '20px',
        boxShadow: 'var(--shadow-card)',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: '10px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          {isRunning ? (
            <Loader2 size={18} className="spin-icon" color="var(--blue)" />
          ) : isComplete ? (
            <CheckCircle2 size={18} color="var(--green)" />
          ) : null}
          <span
            style={{
              fontSize: '0.875rem',
              fontWeight: 600,
              color: 'var(--ink)',
            }}
          >
            {currentStageName
              ? `Processing: ${currentStageName}`
              : isComplete
              ? 'Migration Completed'
              : 'Pipeline Status'}
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          {elapsedSeconds !== undefined && (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '5px',
                fontSize: '0.8125rem',
                color: 'var(--ink-2)',
                fontFamily: 'var(--font-mono)',
              }}
            >
              <Clock size={14} />
              <span>{formatElapsed(elapsedSeconds)}</span>
            </div>
          )}
          <span
            style={{
              fontSize: '0.9375rem',
              fontWeight: 700,
              color: 'var(--ink)',
              fontFamily: 'var(--font-mono)',
            }}
          >
            {normalized}%
          </span>
        </div>
      </div>

      <div
        style={{
          height: '6px',
          background: 'var(--field)',
          borderRadius: 'var(--radius-full)',
          overflow: 'hidden',
          position: 'relative',
        }}
      >
        <div
          style={{
            height: '100%',
            width: `${normalized}%`,
            background: isComplete
              ? 'var(--green)'
              : 'linear-gradient(90deg, var(--primary) 0%, var(--blue) 100%)',
            borderRadius: 'var(--radius-full)',
            transition: 'width 0.4s ease',
          }}
        />
      </div>
    </div>
  );
};

export default MigrationProgress;
