import React from 'react';

interface ToolChipProps {
  label: string;
  icon?: React.ReactNode;
  active?: boolean;
  count?: number | string;
  className?: string;
  onClick?: () => void;
}

export const ToolChip: React.FC<ToolChipProps> = ({
  label,
  icon,
  active = false,
  count,
  className = '',
  onClick,
}) => {
  return (
    <div
      className={`tool-chip ${className}`}
      onClick={onClick}
      style={{
        cursor: onClick ? 'pointer' : 'default',
        background: active ? 'var(--primary-tint)' : 'var(--field)',
        borderColor: active ? 'var(--primary)' : 'var(--line)',
        color: active ? 'var(--primary)' : 'var(--ink-2)',
      }}
    >
      {icon}
      <span>{label}</span>
      {count !== undefined && (
        <span
          style={{
            padding: '1px 5px',
            borderRadius: 'var(--radius-sm)',
            background: 'var(--surface)',
            fontSize: '0.6875rem',
            fontWeight: 700,
            color: 'var(--ink)',
          }}
        >
          {count}
        </span>
      )}
    </div>
  );
};

export default ToolChip;
