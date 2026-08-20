import React, { useEffect, useState, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import { AlertTriangle } from 'lucide-react';
import { api, type Job, type ArtifactItem } from '../api';
import { PipelineStepper } from '../components/execution/PipelineStepper';
import { StageDetailPanel } from '../components/execution/StageDetailPanel';
import { PIPELINE_STAGES, getStageIndex } from '../config/pipeline.config';

export default function JobDetailPage() {
  const { jobId } = useParams<{ jobId: string }>();

  const [job, setJob] = useState<Job | null>(null);
  const [artifacts, setArtifacts] = useState<ArtifactItem[]>([]);
  const [selectedStageId, setSelectedStageId] = useState<string>('DISCOVERY');
  const [loading, setLoading] = useState(true);
  const [resuming, setResuming] = useState(false);
  const [cancelling, setCancelling] = useState(false);

  const loadData = useCallback(async () => {
    if (!jobId) return;
    try {
      const jobData = await api.getJob(jobId);
      setJob(jobData);

      // Auto-follow current or failed stage
      if (jobData.progress?.current_stage) {
        setSelectedStageId(jobData.progress.current_stage);
      } else if (jobData.current_stage) {
        setSelectedStageId(jobData.current_stage);
      }

      const artData = await api.listArtifacts(jobId).catch(() => ({ artifacts: [] }));
      setArtifacts(artData.artifacts || []);
    } catch (e) {
      console.error('Failed to load migration hub data:', e);
    } finally {
      setLoading(false);
    }
  }, [jobId]);

  useEffect(() => {
    loadData();

    // Only set up polling timer if job is currently active or initializing
    if (job && !['RUNNING', 'PENDING', 'PROMOTING'].includes(job.status)) {
      return;
    }

    const interval = setInterval(() => {
      loadData();
    }, 4000);

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

  const isRunning = ['RUNNING', 'PENDING', 'PROMOTING'].includes(job.status);
  const isComplete = ['COMPLETE', 'COMPLETE_WITH_WARNINGS', 'PUBLISHED'].includes(job.status);
  const isFailed = job.status === 'FAILED';

  // Compute completed stages array
  const currentStageKey = job.progress?.current_stage || job.current_stage || 'DISCOVERY';
  const currentIdx = getStageIndex(currentStageKey);
  const completedStageKeys = isComplete
    ? PIPELINE_STAGES.map((s) => s.id)
    : PIPELINE_STAGES.filter((_, idx) => idx < currentIdx).map((s) => s.id);

  // Compute progress percentage
  const totalStages = PIPELINE_STAGES.length;
  const progressPercent = isComplete
    ? 100
    : Math.max(5, Math.round(((completedStageKeys.length + (isRunning ? 0.5 : 0)) / totalStages) * 100));

  const totalObjs = job.progress?.objects_total || job.objects_total || 0;
  const processedObjs = job.progress?.objects_processed || job.objects_processed || 0;
  const succeededObjs = job.progress?.objects_succeeded || job.objects_succeeded || processedObjs;
  const failedObjs = job.progress?.objects_failed || job.objects_failed || 0;
  const confidenceScore = job.validation?.structural_confidence;

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

      {/* ── Interactive Pipeline Stepper ─────────────────────────── */}
      <PipelineStepper
        currentStageId={isRunning ? currentStageKey : undefined}
        selectedStageId={selectedStageId}
        onSelectStage={setSelectedStageId}
        stagesCompleted={completedStageKeys}
        failedStageId={isFailed ? currentStageKey : undefined}
      />

      {/* ── Clicked Stage Detail Panel ───────────────────────────── */}
      <StageDetailPanel
        stageId={selectedStageId}
        jobId={jobId!}
        status={
          isFailed && selectedStageId === currentStageKey
            ? 'FAILED'
            : isRunning && selectedStageId === currentStageKey
              ? 'RUNNING'
              : completedStageKeys.includes(selectedStageId)
                ? 'COMPLETED'
                : 'WAITING'
        }
        durationSeconds={job.duration_seconds}
        stats={{
          objects_discovered: totalObjs,
          processed: processedObjs,
          succeeded: succeededObjs,
          failed: failedObjs,
        }}
        artifacts={artifacts.map((a) => ({ name: a.file_name, path: a.file_path, size: `${Math.round(a.size_bytes / 1024)} KB` }))}
      />


    </div>
  );
}
