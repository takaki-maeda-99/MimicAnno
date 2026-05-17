/**
 * U-A1 — /datasets page: dataset catalog + per-dataset episode table + Annotate modal.
 */
import { useEffect, useState } from "react";
import {
  fetchDatasets,
  fetchDataset,
  postJob,
  type DatasetInfo,
  type DatasetDetail,
  type PostJobBody,
} from "../lib/catalogClient";

// ---------------------------------------------------------------------------
// AnnotateModal
// ---------------------------------------------------------------------------

interface AnnotateModalProps {
  dataset: string;
  onClose: () => void;
  onSubmitted: (jobId: string) => void;
}

function AnnotateModal({ dataset, onClose, onSubmitted }: AnnotateModalProps) {
  const [runSet, setRunSet] = useState(`${dataset}_run_${new Date().toISOString().slice(0, 10).replace(/-/g, "")}`);
  const [robotConfig, setRobotConfig] = useState("configs/robot/so101.yaml");
  const [pipelineConfig, setPipelineConfig] = useState("configs/pipeline/phase4_v5.yaml");
  const [episodeIndices, setEpisodeIndices] = useState("");
  const [gpuIndex, setGpuIndex] = useState("");
  const [variant, setVariant] = useState("4B");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);

    // Parse episode indices
    let parsed_indices: number[] | null = null;
    const trimmed = episodeIndices.trim();
    if (trimmed !== "" && trimmed.toLowerCase() !== "all") {
      try {
        parsed_indices = trimmed
          .split(",")
          .map((s) => s.trim())
          .filter((s) => s !== "")
          .map((s) => {
            const n = parseInt(s, 10);
            if (isNaN(n)) throw new Error(`invalid episode index: ${s}`);
            return n;
          });
      } catch (err) {
        setError(String(err instanceof Error ? err.message : err));
        setSubmitting(false);
        return;
      }
    }

    const gpu = gpuIndex.trim() !== "" ? parseInt(gpuIndex, 10) : null;

    const body: PostJobBody = {
      kind: "annotate",
      dataset,
      run_set: runSet,
      robot_config: robotConfig,
      pipeline_config: pipelineConfig,
      episode_indices: parsed_indices,
      gpu_index: gpu,
      variant,
    };

    try {
      const result = await postJob(body);
      onSubmitted(result.job_id);
    } catch (err) {
      setError(String(err instanceof Error ? err.message : err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div data-testid="annotate-modal" style={{ position: "fixed", top: 0, left: 0, right: 0, bottom: 0, background: "rgba(0,0,0,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000 }}>
      <div style={{ background: "white", padding: 24, borderRadius: 8, minWidth: 400, maxWidth: 600 }}>
        <h2>Annotate Dataset: {dataset}</h2>
        {error && <p style={{ color: "red" }} data-testid="modal-error">{error}</p>}
        <form onSubmit={handleSubmit}>
          <label>
            Run Set Name:<br />
            <input
              data-testid="input-run-set"
              value={runSet}
              onChange={(e) => setRunSet(e.target.value)}
              required
              style={{ width: "100%", marginBottom: 8 }}
            />
          </label>
          <label>
            Robot Config (repo-relative path):<br />
            <input
              data-testid="input-robot-config"
              value={robotConfig}
              onChange={(e) => setRobotConfig(e.target.value)}
              required
              style={{ width: "100%", marginBottom: 8 }}
            />
          </label>
          <label>
            Pipeline Config (repo-relative path):<br />
            <input
              data-testid="input-pipeline-config"
              value={pipelineConfig}
              onChange={(e) => setPipelineConfig(e.target.value)}
              required
              style={{ width: "100%", marginBottom: 8 }}
            />
          </label>
          <label>
            Episode Indices (comma-separated or "all"):<br />
            <input
              data-testid="input-episode-indices"
              value={episodeIndices}
              onChange={(e) => setEpisodeIndices(e.target.value)}
              placeholder="all"
              style={{ width: "100%", marginBottom: 8 }}
            />
          </label>
          <label>
            GPU Index (leave blank for auto):<br />
            <input
              data-testid="input-gpu-index"
              value={gpuIndex}
              onChange={(e) => setGpuIndex(e.target.value)}
              placeholder="auto"
              style={{ width: "100%", marginBottom: 8 }}
            />
          </label>
          <label>
            Variant:<br />
            <select
              data-testid="input-variant"
              value={variant}
              onChange={(e) => setVariant(e.target.value)}
              style={{ marginBottom: 16 }}
            >
              <option value="4B">4B</option>
              <option value="26B">26B</option>
            </select>
          </label>
          <div style={{ display: "flex", gap: 8 }}>
            <button type="submit" disabled={submitting} data-testid="submit-annotate">
              {submitting ? "Submitting…" : "Submit Job"}
            </button>
            <button type="button" onClick={onClose}>Cancel</button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

type PageState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ok"; datasets: DatasetInfo[] };

type DetailState =
  | { kind: "none" }
  | { kind: "loading"; name: string }
  | { kind: "error"; name: string; message: string }
  | { kind: "ok"; detail: DatasetDetail };

type ModalState =
  | { kind: "closed" }
  | { kind: "open"; dataset: string }
  | { kind: "success"; jobId: string };

export default function DatasetsPage() {
  const [state, setState] = useState<PageState>({ kind: "loading" });
  const [detailState, setDetailState] = useState<DetailState>({ kind: "none" });
  const [modal, setModal] = useState<ModalState>({ kind: "closed" });

  useEffect(() => {
    let cancelled = false;
    fetchDatasets()
      .then((datasets) => {
        if (!cancelled) setState({ kind: "ok", datasets });
      })
      .catch((err: unknown) => {
        if (!cancelled)
          setState({ kind: "error", message: String(err instanceof Error ? err.message : err) });
      });
    return () => { cancelled = true; };
  }, []);

  const handleRowClick = (name: string) => {
    if (detailState.kind === "ok" && detailState.detail.name === name) {
      setDetailState({ kind: "none" });
      return;
    }
    setDetailState({ kind: "loading", name });
    fetchDataset(name)
      .then((detail) => setDetailState({ kind: "ok", detail }))
      .catch((err: unknown) =>
        setDetailState({ kind: "error", name, message: String(err instanceof Error ? err.message : err) }),
      );
  };

  if (state.kind === "loading") {
    return <div data-testid="datasets-loading">Loading datasets…</div>;
  }
  if (state.kind === "error") {
    return <div data-testid="datasets-error">Error: {state.message}</div>;
  }

  const { datasets } = state;

  return (
    <div data-testid="datasets-page">
      <h1>Datasets</h1>
      {modal.kind === "success" && (
        <div data-testid="job-queued-toast" style={{ background: "#d4edda", padding: 8, marginBottom: 8 }}>
          Job queued: <strong>{modal.jobId}</strong>.{" "}
          <a href="/?page=jobs">View jobs</a>
          <button onClick={() => setModal({ kind: "closed" })}>Dismiss</button>
        </div>
      )}
      <table data-testid="datasets-table" style={{ borderCollapse: "collapse", width: "100%" }}>
        <thead>
          <tr>
            <th>Name</th>
            <th>Episodes</th>
            <th>Annotated</th>
            <th>Robot</th>
            <th>Task</th>
            <th>Last Modified</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          {datasets.map((ds) => (
            <>
              <tr key={ds.name} onClick={() => handleRowClick(ds.name)} style={{ cursor: "pointer" }}>
                <td data-testid={`ds-name-${ds.name}`}>{ds.name}</td>
                <td data-testid={`ds-ep-count-${ds.name}`}>{ds.ep_count}</td>
                <td data-testid={`ds-annotated-${ds.name}`}>{ds.annotated_ep_count}</td>
                <td>{ds.robot_hint ?? "—"}</td>
                <td>{ds.task_text_hint ?? "—"}</td>
                <td>{ds.last_modified}</td>
                <td>
                  <button
                    data-testid={`annotate-btn-${ds.name}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      setModal({ kind: "open", dataset: ds.name });
                    }}
                  >
                    Annotate
                  </button>
                </td>
              </tr>
              {detailState.kind === "ok" && detailState.detail.name === ds.name && (
                <tr key={`${ds.name}-detail`}>
                  <td colSpan={7}>
                    <table data-testid={`ep-table-${ds.name}`} style={{ width: "100%", borderCollapse: "collapse" }}>
                      <thead>
                        <tr>
                          <th>Episode</th>
                          <th>FPS</th>
                          <th>Runs</th>
                        </tr>
                      </thead>
                      <tbody>
                        {detailState.detail.episodes.map((ep) => (
                          <tr key={ep.idx}>
                            <td>{ep.idx}</td>
                            <td>{ep.fps ?? "—"}</td>
                            <td>
                              {ep.runs.length === 0 ? (
                                <span>—</span>
                              ) : (
                                ep.runs.map((r, i) => (
                                  <span key={i} style={{ marginRight: 4 }}>
                                    [{r.run_set}] {r.canonical.slice(0, 20)}
                                  </span>
                                ))
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </td>
                </tr>
              )}
              {detailState.kind === "loading" && detailState.name === ds.name && (
                <tr key={`${ds.name}-loading`}>
                  <td colSpan={7} data-testid={`ep-table-loading-${ds.name}`}>Loading episodes…</td>
                </tr>
              )}
              {detailState.kind === "error" && detailState.name === ds.name && (
                <tr key={`${ds.name}-error`}>
                  <td colSpan={7} data-testid={`ep-table-error-${ds.name}`}>Error: {detailState.message}</td>
                </tr>
              )}
            </>
          ))}
        </tbody>
      </table>

      {modal.kind === "open" && (
        <AnnotateModal
          dataset={modal.dataset}
          onClose={() => setModal({ kind: "closed" })}
          onSubmitted={(jobId) => setModal({ kind: "success", jobId })}
        />
      )}
    </div>
  );
}
