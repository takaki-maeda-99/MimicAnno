/**
 * Phase 5 B r1 T13.6-T13.9 — segment list with optional phase dropdown.
 * Phase 5 B r3 — reviewed column becomes a checkbox when editable.
 *
 * Read-only in static (?api unset) mode; editable when apiEnabled=true and
 * a labelset is loaded. Edit flow is driven by the parent (RunViewer):
 * parent owns optimistic state, this component only emits onPhaseEdit /
 * onReviewedToggle and reflects pending/disabled state via props.
 */
import { useState, useEffect } from "react";
import type { SubtaskSegment } from "../lib/manifest";
import type { LabelSetDoc } from "../lib/labelsetClient";
import type { PatchResult } from "../lib/editClient";
import type { ReviewedPatchResult } from "../lib/reviewedClient";

export interface SegmentTableToast {
  level: "conflict" | "invalid" | "error" | "sync_warning";
  message: string;
}

export interface SegmentTableProps {
  segments: SubtaskSegment[];
  apiEnabled: boolean;
  labelset: LabelSetDoc | null;
  onPhaseEdit: (
    segmentId: string,
    newPhase: string,
    oldPhase: string,
  ) => Promise<PatchResult>;
  onReviewedToggle: (
    segmentId: string,
    newReviewed: boolean,
  ) => Promise<ReviewedPatchResult>;
  editInFlight: boolean;
  staleRun: boolean;
  toast?: SegmentTableToast;
}

function fmt(n: number): string {
  return n.toFixed(2);
}

export default function SegmentTable(props: SegmentTableProps) {
  const {
    segments,
    apiEnabled,
    labelset,
    onPhaseEdit,
    onReviewedToggle,
    editInFlight,
    staleRun,
    toast,
  } = props;
  const editable = apiEnabled && labelset !== null;
  const disabled = editInFlight || staleRun;

  return (
    <div className="segment-table">
      {toast && (
        <div
          role="alert"
          className={`toast toast-${toast.level}`}
          aria-live="polite"
        >
          {toast.message}
          {staleRun && (
            <>
              {" "}
              <button
                onClick={() => {
                  // Bug found in UI smoke: window.location.reload() with the
                  // OLD ?hash still in the URL hits "no run for episode_id=X
                  // hash=<stale>". staleRun is by definition "the hash I have
                  // is one revision behind", so the recovery is to drop ?hash
                  // and let the viewer pick the latest run for this episode.
                  const url = new URL(window.location.href);
                  url.searchParams.delete("hash");
                  window.location.href = url.toString();
                }}
              >
                reload
              </button>
            </>
          )}
        </div>
      )}
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>segment</th>
            <th>start–end (s)</th>
            <th>phase</th>
            <th>conf</th>
            <th>reviewed</th>
            <th>source</th>
          </tr>
        </thead>
        <tbody>
          {segments.map((s, i) => (
            <SegmentRow
              key={s.segment_id}
              idx={i + 1}
              segment={s}
              editable={editable}
              labelset={labelset}
              disabled={disabled}
              onPhaseEdit={onPhaseEdit}
              onReviewedToggle={onReviewedToggle}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SegmentRow({
  idx,
  segment,
  editable,
  labelset,
  disabled,
  onPhaseEdit,
  onReviewedToggle,
}: {
  idx: number;
  segment: SubtaskSegment;
  editable: boolean;
  labelset: LabelSetDoc | null;
  disabled: boolean;
  onPhaseEdit: (
    segmentId: string,
    newPhase: string,
    oldPhase: string,
  ) => Promise<PatchResult>;
  onReviewedToggle: (
    segmentId: string,
    newReviewed: boolean,
  ) => Promise<ReviewedPatchResult>;
}) {
  // Controlled <select>: local optimistic value, reset on parent's segment
  // change (after server re-fetches). Rollback = setLocalPhase(oldPhase)
  // in the catch path. We keep oldPhase derived from props each render so
  // the rollback always reverts to the last server-confirmed value.
  const [localPhase, setLocalPhase] = useState(segment.phase);
  useEffect(() => {
    setLocalPhase(segment.phase);
  }, [segment.phase]);

  // Optimistic reviewed state: flips immediately, rolls back on non-ok.
  const [localReviewed, setLocalReviewed] = useState(segment.reviewed);
  useEffect(() => {
    setLocalReviewed(segment.reviewed);
  }, [segment.reviewed]);

  const onChange = async (e: React.ChangeEvent<HTMLSelectElement>) => {
    const newPhase = e.target.value;
    const oldPhase = segment.phase;
    if (newPhase === oldPhase) return;
    setLocalPhase(newPhase);
    try {
      const r = await onPhaseEdit(segment.segment_id, newPhase, oldPhase);
      if (r.kind !== "ok") {
        setLocalPhase(oldPhase);
      }
      // On "ok", parent re-fetch will update segment.phase → effect resets us.
    } catch {
      setLocalPhase(oldPhase);
    }
  };

  const onReviewedChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const newReviewed = e.target.checked;
    setLocalReviewed(newReviewed);
    try {
      const r = await onReviewedToggle(segment.segment_id, newReviewed);
      if (r.kind !== "ok") {
        setLocalReviewed(!newReviewed);
      }
    } catch {
      setLocalReviewed(!newReviewed);
    }
  };

  return (
    <tr>
      <td>{idx}</td>
      <td><code>{segment.segment_id}</code></td>
      <td>
        {fmt(segment.start_time)}–{fmt(segment.end_time)}
      </td>
      <td>
        {editable && labelset !== null ? (
          <select
            value={localPhase}
            onChange={onChange}
            disabled={disabled}
            aria-label={`phase for ${segment.segment_id}`}
          >
            {labelset.labels.map((l) => (
              <option key={l.id} value={l.id}>
                {l.id}
              </option>
            ))}
          </select>
        ) : (
          <span>{segment.phase}</span>
        )}
      </td>
      <td>{fmt(segment.overall_confidence)}</td>
      <td>
        {editable ? (
          <input
            type="checkbox"
            checked={localReviewed}
            disabled={disabled}
            aria-label={`reviewed for ${segment.segment_id}`}
            onChange={onReviewedChange}
          />
        ) : (
          <span>{segment.reviewed ? "✓" : "–"}</span>
        )}
      </td>
      <td>{segment.label_source}</td>
    </tr>
  );
}
