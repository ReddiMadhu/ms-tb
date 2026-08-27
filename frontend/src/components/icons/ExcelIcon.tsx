import React from 'react';

export interface ExcelIconProps {
  size?: number | string;
  className?: string;
  style?: React.CSSProperties;
}

export function ExcelIcon({
  size = 20,
  className,
  style,
}: ExcelIconProps) {
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
      {/* Background Sheet Container */}
      <rect x="7" y="3" width="22" height="26" rx="2.5" fill="#107C41" />
      {/* Sheet grid cells */}
      <path d="M19 7H25V11H19V7Z" fill="#33C481" />
      <path d="M19 14H25V18H19V14Z" fill="#33C481" />
      <path d="M19 21H25V25H19V21Z" fill="#33C481" />
      <path d="M13 7H17V11H13V7Z" fill="#21A366" />
      <path d="M13 14H17V18H13V14Z" fill="#21A366" />
      <path d="M13 21H17V25H13V21Z" fill="#21A366" />
      
      {/* Front Excel 'X' Badge */}
      <rect x="3" y="7" width="14" height="18" rx="2.5" fill="#0E5C2F" />
      <path
        d="M6.8 11.2L9.2 16L6.8 20.8H8.7L10.1 17.6L11.5 20.8H13.4L11 16L13.4 11.2H11.5L10.1 14.4L8.7 11.2H6.8Z"
        fill="white"
      />
    </svg>
  );
}

export default ExcelIcon;
