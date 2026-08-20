import React from 'react';

interface KpiCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon?: React.ReactNode;
  accentColor?: string;
  trend?: {
    value: string;
    positive?: boolean;
  };
  onClick?: () => void;
  className?: string;
}

export const KpiCard: React.FC<KpiCardProps> = ({
  title,
  value,
  subtitle,
  icon,
  accentColor = 'var(--primary)',
  trend,
  onClick,
  className = '',
}) => {
  return (
    <div
      className={`kpi-card ${onClick ? 'cursor-pointer' : ''} ${className}`}
      onClick={onClick}
      style={{ cursor: onClick ? 'pointer' : 'default' }}
    >
      <div className="kpi-card-accent" style={{ backgroundColor: accentColor }} />
      <div className="kpi-card-header">
        <span>{title}</span>
        {icon && <span style={{ color: accentColor }}>{icon}</span>}
      </div>
      <div className="kpi-card-value">
        {value}
        {trend && (
          <span
            style={{
              fontSize: '0.75rem',
              fontWeight: 600,
              color: trend.positive ? 'var(--green)' : 'var(--red)',
            }}
          >
            {trend.value}
          </span>
        )}
      </div>
      {subtitle && <div className="kpi-card-subtitle">{subtitle}</div>}
    </div>
  );
};

export default KpiCard;
