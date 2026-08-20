// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Status Configuration — Unified status system
// Every status has: icon, label, colorKey, description
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

export type MigrationStatus =
  | 'PENDING'
  | 'RUNNING'
  | 'PROMOTING'
  | 'COMPLETE'
  | 'COMPLETE_WITH_WARNINGS'
  | 'NEEDS_REVIEW'
  | 'BLOCKED'
  | 'FAILED'
  | 'CANCELLED'
  | 'PUBLISHED';

export type StageStatus =
  | 'WAITING'
  | 'RUNNING'
  | 'COMPLETED'
  | 'WARNING'
  | 'FAILED'
  | 'SKIPPED';

export type ReviewSeverity = 'blocker' | 'warning' | 'info';

export interface StatusConfig {
  label: string;
  icon: string;            // lucide icon name
  colorVar: string;        // CSS custom property
  tintVar: string;         // CSS tint custom property
  description: string;
}

export const JOB_STATUS: Record<string, StatusConfig> = {
  PENDING:    { label: 'Queued',      icon: 'Clock',         colorVar: 'var(--ink-3)',    tintVar: 'var(--hover)',        description: 'Waiting to start' },
  RUNNING:    { label: 'Running',     icon: 'Loader2',       colorVar: 'var(--blue)',     tintVar: 'var(--blue-tint)',    description: 'Active processing' },
  PROMOTING:  { label: 'Promoting',   icon: 'ArrowUpCircle', colorVar: 'var(--blue)',     tintVar: 'var(--blue-tint)',    description: 'Promoting to production' },
  COMPLETE:   { label: 'Completed',   icon: 'CheckCircle2',  colorVar: 'var(--green)',    tintVar: 'var(--green-tint)',   description: 'Finished successfully' },
  COMPLETE_WITH_WARNINGS: { label: 'Warnings', icon: 'AlertTriangle', colorVar: 'var(--yellow)', tintVar: 'var(--yellow-tint)', description: 'Finished with warnings' },
  NEEDS_REVIEW: { label: 'Review',   icon: 'AlertTriangle', colorVar: 'var(--yellow)',   tintVar: 'var(--yellow-tint)',  description: 'Requires human attention' },
  BLOCKED:    { label: 'Blocked',     icon: 'Ban',           colorVar: 'var(--red)',      tintVar: 'var(--red-tint)',     description: 'Cannot proceed' },
  FAILED:     { label: 'Failed',      icon: 'XCircle',       colorVar: 'var(--red)',      tintVar: 'var(--red-tint)',     description: 'Error occurred' },
  CANCELLED:  { label: 'Cancelled',   icon: 'MinusCircle',   colorVar: 'var(--ink-3)',    tintVar: 'var(--hover)',        description: 'Stopped by user' },
  PUBLISHED:  { label: 'Published',   icon: 'CheckCheck',    colorVar: 'var(--green)',    tintVar: 'var(--green-tint)',   description: 'Deployed to target' },
};

export const STAGE_STATUS: Record<string, StatusConfig> = {
  WAITING:   { label: 'Waiting',   icon: 'Circle',        colorVar: 'var(--ink-3)',  tintVar: 'var(--hover)',        description: 'Not yet started' },
  RUNNING:   { label: 'Running',   icon: 'Loader2',       colorVar: 'var(--blue)',   tintVar: 'var(--blue-tint)',    description: 'In progress' },
  COMPLETED: { label: 'Completed', icon: 'CheckCircle2',  colorVar: 'var(--green)',  tintVar: 'var(--green-tint)',   description: 'Finished' },
  WARNING:   { label: 'Warning',   icon: 'AlertTriangle', colorVar: 'var(--yellow)', tintVar: 'var(--yellow-tint)',  description: 'Finished with warnings' },
  FAILED:    { label: 'Failed',    icon: 'XCircle',       colorVar: 'var(--red)',    tintVar: 'var(--red-tint)',     description: 'Error' },
  SKIPPED:   { label: 'Skipped',   icon: 'SkipForward',   colorVar: 'var(--ink-3)',  tintVar: 'var(--hover)',        description: 'Skipped' },
};

export const REVIEW_SEVERITY: Record<string, StatusConfig> = {
  blocker: { label: 'Critical',      icon: 'OctagonX',      colorVar: 'var(--red)',    tintVar: 'var(--red-tint)',    description: 'Blocks publish' },
  warning: { label: 'Warning',       icon: 'AlertTriangle', colorVar: 'var(--yellow)', tintVar: 'var(--yellow-tint)', description: 'Requires attention' },
  info:    { label: 'Informational', icon: 'Info',          colorVar: 'var(--blue)',   tintVar: 'var(--blue-tint)',   description: 'For awareness' },
};

export function getJobStatus(status: string): StatusConfig {
  return JOB_STATUS[status] ?? JOB_STATUS.PENDING;
}

export function getStageStatus(status: string): StatusConfig {
  return STAGE_STATUS[status] ?? STAGE_STATUS.WAITING;
}

export function getSeverityConfig(severity: string): StatusConfig {
  return REVIEW_SEVERITY[severity] ?? REVIEW_SEVERITY.info;
}
