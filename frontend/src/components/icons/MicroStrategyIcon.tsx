import React from 'react';

export interface MicroStrategyIconProps {
  size?: number | string;
  className?: string;
  style?: React.CSSProperties;
  monochrome?: boolean;
}

export function MicroStrategyIcon({
  size = 22,
  className,
  style,
  monochrome = false,
}: MicroStrategyIconProps) {
  const color = monochrome ? 'currentColor' : '#d9272e';

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      style={{ display: 'inline-block', verticalAlign: 'middle', flexShrink: 0, ...style }}
    >
      <rect x="2" y="4" width="5.5" height="24" rx="2.75" fill={color} />
      <rect x="10" y="9.5" width="5.5" height="18.5" rx="2.75" fill={color} />
      <rect x="17.5" y="9.5" width="5.5" height="18.5" rx="2.75" fill={color} />
      <rect x="25" y="4" width="5.5" height="24" rx="2.75" fill={color} />
    </svg>
  );
}

export default MicroStrategyIcon;
