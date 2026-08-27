import React from 'react';

export interface TableauIconProps {
  size?: number | string;
  className?: string;
  style?: React.CSSProperties;
  monochrome?: boolean;
}

export function TableauIcon({
  size = 20,
  className,
  style,
  monochrome = false,
}: TableauIconProps) {
  if (monochrome) {
    return (
      <svg
        width={size}
        height={size}
        viewBox="0 0 100 100"
        fill="currentColor"
        className={className}
        style={{ display: 'inline-block', verticalAlign: 'middle', flexShrink: 0, ...style }}
      >
        {/* Center */}
        <rect x="46" y="32" width="8" height="36" rx="1.5" />
        <rect x="32" y="46" width="36" height="8" rx="1.5" />
        {/* Top */}
        <rect x="47.5" y="6" width="5" height="24" rx="1" />
        <rect x="38" y="15.5" width="24" height="5" rx="1" />
        {/* Bottom */}
        <rect x="47.5" y="70" width="5" height="24" rx="1" />
        <rect x="38" y="79.5" width="24" height="5" rx="1" />
        {/* Left */}
        <rect x="6" y="47.5" width="24" height="5" rx="1" />
        <rect x="15.5" y="38" width="5" height="24" rx="1" />
        {/* Right */}
        <rect x="70" y="47.5" width="24" height="5" rx="1" />
        <rect x="79.5" y="38" width="5" height="24" rx="1" />
        {/* Top Left */}
        <rect x="23" y="16" width="4" height="18" rx="1" />
        <rect x="16" y="23" width="18" height="4" rx="1" />
        {/* Top Right */}
        <rect x="73" y="16" width="4" height="18" rx="1" />
        <rect x="66" y="23" width="18" height="4" rx="1" />
        {/* Bottom Left */}
        <rect x="23" y="66" width="4" height="18" rx="1" />
        <rect x="16" y="73" width="18" height="4" rx="1" />
        {/* Bottom Right */}
        <rect x="73" y="66" width="4" height="18" rx="1" />
        <rect x="66" y="73" width="18" height="4" rx="1" />
      </svg>
    );
  }

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 100 100"
      className={className}
      style={{ display: 'inline-block', verticalAlign: 'middle', flexShrink: 0, ...style }}
    >
      {/* Center Plus - Coral Red */}
      <rect x="46" y="32" width="8" height="36" rx="1.5" fill="#E84A36" />
      <rect x="32" y="46" width="36" height="8" rx="1.5" fill="#E84A36" />

      {/* Top Plus - Slate Blue */}
      <rect x="47.5" y="6" width="5" height="24" rx="1" fill="#4E79A7" />
      <rect x="38" y="15.5" width="24" height="5" rx="1" fill="#4E79A7" />

      {/* Bottom Plus - Orange */}
      <rect x="47.5" y="70" width="5" height="24" rx="1" fill="#F28E2B" />
      <rect x="38" y="79.5" width="24" height="5" rx="1" fill="#F28E2B" />

      {/* Left Plus - Deep Navy */}
      <rect x="6" y="47.5" width="24" height="5" rx="1" fill="#244E66" />
      <rect x="15.5" y="38" width="5" height="24" rx="1" fill="#244E66" />

      {/* Right Plus - Red Orange */}
      <rect x="70" y="47.5" width="24" height="5" rx="1" fill="#E15759" />
      <rect x="79.5" y="38" width="5" height="24" rx="1" fill="#E15759" />

      {/* Top-Left Plus - Amber */}
      <rect x="23" y="16" width="4" height="18" rx="1" fill="#EDC948" />
      <rect x="16" y="23" width="18" height="4" rx="1" fill="#EDC948" />

      {/* Top-Right Plus - Teal */}
      <rect x="73" y="16" width="4" height="18" rx="1" fill="#76B7B2" />
      <rect x="66" y="23" width="18" height="4" rx="1" fill="#76B7B2" />

      {/* Bottom-Left Plus - Coral Pink */}
      <rect x="23" y="66" width="4" height="18" rx="1" fill="#FF9DA7" />
      <rect x="16" y="73" width="18" height="4" rx="1" fill="#FF9DA7" />

      {/* Bottom-Right Plus - Steel Blue */}
      <rect x="73" y="66" width="4" height="18" rx="1" fill="#59A14F" />
      <rect x="66" y="73" width="18" height="4" rx="1" fill="#59A14F" />
    </svg>
  );
}

export default TableauIcon;
