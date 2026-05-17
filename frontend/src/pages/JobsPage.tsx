/**
 * U-A1 — /jobs page: job list + per-job detail panel with log tail.
 */
import { useEffect, useRef, useState } from "react";
import {
  fetchJobs,
  fetchJob,
  deleteJob,
  type JobSummary,
  type JobDetail,
} from "../lib/catalogClient";

const STATUS_COLORS: Record<string, string> = {
  queued: "#6c757d",
  running: "#0d6efd",
  done: "#198754",
  failed: "#dc3545",
  cancelled: "#6c757d",
};

function StatusBadge({ status }: { status: string }) {
  return (
    <span
      data-testid={`status-badge-${status}`}
      style={{
        background: STATUS_COLORS[status] ?? "#aaa",
        color: "white",
        padding: "2px 8px",
        borderRadius: 4,
        fontSize: "0.85em",
      }}
    >
      {status}
    </span>
  );
}

interface DetailPanelProps {
  jobId: string;
  onCancel: () => void;
  onBack: () => void;
}

function DetailPanel({ jobId, onCancel, onBack }: DetailPanelProps) {
  const [detail, setDetail] = useState<JobDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const logRef = useRef<HTMLPreElement>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      fetchJob(jobId)
        .then((d) => { if (!cancelled) setDetail(d); })
        .catch((err: unknown) => { if (!cancelled) setError(String(err instanceof Error ? err.message : err)); });
    };
    load();
    // Poll every 3s if running/queued
    const interval = setInterval(() => {
      fetchJob(jobId)
        .then((d) => {
          if (!cancelled) {
            setDetail(d);
            if (d.status === "done" || d.status === "failed" || d.status === "cancelled") {
              clearInterval(interval);
            }
          }
        })
        .catch(() => {/* ignore poll errors */});
    }, 3000);
    return () => { cancelled = true; clearInterval(interval); };
  }, [jobId]);

  const handleCancel = async () => {
    setCancelling(true);
    try {
      await deleteJob(jobId);
      onCancel();
    } catch (err) {
      setError(String(err instanceof Error ? err.message : err));
    } finally {
      setCancelling(false);
    }
  };

  if (error) {
    return <div data-testid="job-detail-error">Error: {error}</div>;
  }
  if (!detail) {
    return <div data-testid="job-detail-loading">Loading job details…</div>;
  }

  return (
    <div data-testid="job-detail-panel">
      <button onClick={onBack}>← Back</button>
      <h2>Job: {detail.job_id}</h2>
      <p><StatusBadge status={detail.status} /> — {detail.dataset}</p>
      {detail.progress_pct !== null && (
        <p>Progress: {detail.progress_pct}%</p>
      )}
      {detail.error && (
        <p style={{ color: "red" }}>Error: {detail.error.reason} {detail.error.detail && `(${detail.error.detail})`}</p>
      )}
      <p>Run set: {detail.run_set}</p>
      <p>Episodes: {detail.episode_indices.join(", ")}</p>
      {detail.status === "running" && (
        <button
          data-testid="cancel-job-btn"
          onClick={handleCancel}
          disabled={cancelling}
        >
          {cancelling ? "Cancelling…" : "Cancel Job"}
        </button>
      )}
      <h3>Log (last 200 lines)</h3>
      <pre
        ref={logRef}
        data-testid="job-log-tail"
        style={{ background: "#222", color: "#eee", padding: 8, maxHeight: 400, overflow: "auto", fontSize: "0.8em" }}
      >
        {detail.log_tail.join("\n") || "(no log yet)"}
      </pre>
    </div>
  );
}

export default function JobsPage() {
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);

  const loadJobs = () => {
    fetchJobs()
      .then((j) => { setJobs(j); setLoading(false); })
      .catch((err: unknown) => {
        setError(String(err instanceof Error ? err.message : err));
        setLoading(false);
      });
  };

  useEffect(() => {
    loadJobs();
    const interval = setInterval(loadJobs, 5000);
    return () => clearInterval(interval);
  }, []);

  if (selectedJobId) {
    return (
      <DetailPanel
        jobId={selectedJobId}
        onCancel={() => { setSelectedJobId(null); loadJobs(); }}
        onBack={() => setSelectedJobId(null)}
      />
    );
  }

  if (loading) return <div data-testid="jobs-loading">Loading jobs…</div>;
  if (error) return <div data-testid="jobs-error">Error: {error}</div>;

  return (
    <div data-testid="jobs-page">
      <h1>Jobs</h1>
      {jobs.length === 0 && (
        <p data-testid="jobs-empty">No jobs yet. Submit an annotate job from the Datasets page.</p>
      )}
      <table data-testid="jobs-table" style={{ borderCollapse: "collapse", width: "100%" }}>
        <thead>
          <tr>
            <th>Job ID</th>
            <th>Status</th>
            <th>Dataset</th>
            <th>Progress</th>
            <th>Started</th>
            <th>Finished</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          {jobs.map((job) => (
            <tr key={job.job_id} onClick={() => setSelectedJobId(job.job_id)} style={{ cursor: "pointer" }}>
              <td data-testid={`job-id-${job.job_id}`}>{job.job_id}</td>
              <td><StatusBadge status={job.status} /></td>
              <td>{job.dataset}</td>
              <td>{job.progress_pct !== null ? `${job.progress_pct}%` : "—"}</td>
              <td>{job.started_at ?? "—"}</td>
              <td>{job.finished_at ?? "—"}</td>
              <td>
                <button
                  data-testid={`detail-btn-${job.job_id}`}
                  onClick={(e) => { e.stopPropagation(); setSelectedJobId(job.job_id); }}
                >
                  Details
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
