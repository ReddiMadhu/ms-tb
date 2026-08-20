import React from 'react';

interface ProgressRingProps {
  progress: number; // 0 to 100 or 0.0 to 1.0
  size?: number;
  strokeWidth?: number;
  color?: string;
  backgroundColor?: string;
  label?: string;
  showPercent?: boolean;
}

export const ProgressRing: React.FC<ProgressRingProps> = ({
  progress,
  size = 64,
  strokeWidth = 6,
  color = 'var(--primary)',
  backgroundColor = 'var(--field)',
  label,
  showPercent = true,
}) => {
  // Normalize progress to 0-100
  const normalizedProgress = progress <= 1.0 ? Math.round(progress * 100) : Math.min(100, Math.max(0, Math.round(progress)));
  const radius = (size - strokeWidth) / 2;
  const circumference = radius * 2 * Math.PI;
  const offset = circumference - (normalizedProgress / 100) * circumference;

  return (
    <div
      style={{
        display: 'inline-flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: '6px',
      }}
    >
      <div style={{ position: 'relative', width: size, height: size }}>
        <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
          {/* Background circle */}
          <circle
            stroke={backgroundColor}
            fill="transparent"
            strokeWidth={strokeWidth}
            r={radius}
            cx={size / 2}
            cy={size / 2}
          />
          {/* Progress circle */}
          <circle
            stroke={color}
            fill="transparent"
            strokeWidth={strokeWidth}
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            strokeLinecap="round"
            style={{ transition: 'stroke-dashoffset 0.6s ease' }}
            r={radius}
            cx={size / 2}
            cy={size / 2}
          />
        </svg>
        {showPercent && (
          <div
            style={{
              position: 'absolute',
              inset: 0,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: size < 60 ? '0.75rem' : '0.875rem',
              fontWeight: 700,
              color: 'var(--ink)',
              fontFamily: 'var(--font-mono)',
            }}
          >
            {normalizedProgress}%
          </div>
        )}
      </div>
      {label && (
        <span
          style={{
            fontSize: '0.75rem',
            color: 'var(--ink-2)',
            fontWeight: 500,
          }}
        >
          {label}
        </span>
      )}
    </div>
  );
};

export default ProgressRing;
