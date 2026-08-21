import React, { useEffect, useState, useCallback, useRef } from 'react';
import { useParams, Link } from 'react-router-dom';
import { AlertTriangle } from 'lucide-react';
import { api, type Job, type ArtifactItem } from '../api';
import { PipelineStepper } from '../components/execution/PipelineStepper';
import { PhaseContentPanel } from '../components/execution/PhaseContentPanel';
import {
  PIPELINE_STAGES,
  PIPELINE_PHASES,
  getStageIndex,
  getPhaseForStage,
  isJobTerminal,
  isJobRunning,
} from '../config/pipeline.config';

export default function JobDetailPage() {
  const { jobId } = useParams<{ jobId: string }>();

  const [job, setJob] = useState<Job | null>(null);
  const [selectedPhaseId, setSelectedPhaseId] = useState<string>('EXTRACTION_CATALOG');
  const [loading, setLoading] = useState(true);
  const [resuming, setResuming] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const userSelectedPhaseRef = useRef<boolean>(false);

  const loadData = useCallback(async () => {
    if (!jobId) return;
    try {
      const jobData = await api.getJob(jobId);
      setJob(jobData);

      // Keep stepper focused on the currently executing/loading phase while job is running
      const currentStage = jobData.progress?.current_stage || jobData.current_stage;
      if (currentStage) {
        const phase = getPhaseForStage(currentStage);
        if (phase && (isJobRunning(jobData.status) || !userSelectedPhaseRef.current)) {
          setSelectedPhaseId(phase.id);
        }
      }
    } catch (e) {
      console.error('Failed to load migration hub data:', e);
    } finally {
      setLoading(false);
    }
  }, [jobId]);

  useEffect(() => {
    loadData();

    // Poll continuously while job is in-progress (not terminal)
    const terminal = job && isJobTerminal(job.status);
    if (terminal) {
      return;
    }

    const interval = setInterval(() => {
      loadData();
    }, 2000);

    return () => clearInterval(interval);
  }, [loadData, job?.status]);

  if (loading && !job) {
    return (
      <div style={{ maxWidth: '1440px', margin: '0 auto' }}>
        <div className="shimmer" style={{ height: 40, width: '40%', borderRadius: 8, marginBottom: 20 }} />
        <div className="shimmer" style={{ height: 80, borderRadius: 12, marginBottom: 24 }} />
        <div className="shimmer" style={{ height: 160, borderRadius: 12, marginBottom: 24 }} />
      </div>
    );
  }

  if (!job) {
    return (
      <div className="empty-state" style={{ maxWidth: '600px', margin: '60px auto' }}>
        <AlertTriangle size={48} color="var(--red)" />
        <h3 style={{ marginTop: 16 }}>Migration Job Not Found</h3>
        <p style={{ color: 'var(--ink-2)' }}>
          Job ID <code className="mono">{jobId}</code> does not exist or has expired.
        </p>
        <Link to="/" className="btn btn-secondary" style={{ marginTop: 16 }}>
          Return to Workspace
        </Link>
      </div>
    );
  }

  const isRunning = isJobRunning(job.status);
  const isComplete = ['COMPLETE', 'COMPLETE_WITH_WARNINGS', 'PUBLISHED'].includes(job.status);
  const isFailed = job.status === 'FAILED';

  // Compute per-stage status map across all 20 stages
  const currentStageKey = job.progress?.current_stage || job.current_stage || 'DISCOVERY';
  const currentIdx = getStageIndex(currentStageKey);

  const stageStatuses: Record<string, string> = {};
  PIPELINE_STAGES.forEach((s, idx) => {
    if (isComplete) {
      stageStatuses[s.id] = 'COMPLETED';
    } else if (isFailed && s.id === currentStageKey) {
      stageStatuses[s.id] = 'FAILED';
    } else if (idx < currentIdx) {
      stageStatuses[s.id] = 'COMPLETED';
    } else if (s.id === currentStageKey && isRunning) {
      stageStatuses[s.id] = 'RUNNING';
    } else {
      stageStatuses[s.id] = 'WAITING';
    }
  });

  const handleResume = async () => {
    if (!jobId) return;
    setResuming(true);
    try {
      await api.resumeJob(jobId);
      await loadData();
    } catch (e) {
      alert('Failed to resume job from checkpoint');
    } finally {
      setResuming(false);
    }
  };

  const handleCancel = async () => {
    if (!jobId || !window.confirm('Are you sure you want to cancel this migration job?')) return;
    setCancelling(true);
    try {
      await api.cancelJob(jobId);
      await loadData();
    } catch (e) {
      alert('Failed to cancel job');
    } finally {
      setCancelling(false);
    }
  };

  return (
    <div style={{ maxWidth: '1440px', margin: '0 auto' }}>

      {/* ── Failure Banner (if any) ──────────────────────────────── */}
      {isFailed && (
        <div
          style={{
            padding: '16px 20px',
            background: 'var(--red-tint)',
            border: '1px solid var(--red)',
            borderRadius: 'var(--radius-lg)',
            marginBottom: '24px',
            display: 'flex',
            alignItems: 'flex-start',
            gap: '12px',
          }}
        >
          <AlertTriangle size={20} color="var(--red)" style={{ marginTop: '2px', flexShrink: 0 }} />
          <div style={{ flex: 1 }}>
            <h4 style={{ margin: 0, color: 'var(--red)', fontSize: '0.9375rem', fontWeight: 600 }}>
              Migration Interrupted: Checkpoint Preserved
            </h4>
            <p style={{ margin: '4px 0 10px 0', fontSize: '0.8125rem', color: 'var(--ink)' }}>
              {job.error_message ||
                'Pipeline halted due to an unexpected upstream schema exception. Completed stages and IR compilation cache are preserved.'}
            </p>
            <button
              onClick={handleResume}
              className="btn btn-primary"
              style={{ padding: '6px 14px', fontSize: '0.75rem' }}
            >
              Resume from Last Checkpoint
            </button>
          </div>
        </div>
      )}

      {/* ── 4-Node Pipeline Stepper ──────────────────────────────── */}
      <PipelineStepper
        selectedPhaseId={selectedPhaseId}
        onSelectPhase={(phaseId) => {
          userSelectedPhaseRef.current = true;
          setSelectedPhaseId(phaseId);
        }}
        stageStatuses={stageStatuses}
      />

      {/* ── Phase Content Panel ──────────────────────────────────── */}
      <PhaseContentPanel
        phaseId={selectedPhaseId}
        stageStatuses={stageStatuses}
      />

    </div>
  );
}
