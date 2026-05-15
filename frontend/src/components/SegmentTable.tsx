/**
 * Phase 5 B r1 T13.6-T13.9 — segment list with optional phase dropdown.
 * Phase 5 B r3 — reviewed column becomes a checkbox when editable.
 * Phase 5 B r4 — verb/object/target/failure_flags columns editable on blur.
 *
 * Read-only in static (?api unset) mode; editable when apiEnabled=true and
 * a labelset is loaded. Edit flow is driven by the parent (RunViewer):
 * parent owns optimistic state, this component only emits onPhaseEdit /
 * onReviewedToggle / onLabelsEdit and reflects pending/disabled state via props.
 */
import { useState, useEffect } from "react";
import type { SubtaskSegment } from "../lib/manifest";
import type { LabelSetDoc } from "../lib/labelsetClient";
import type { PatchResult } from "../lib/editClient";
import type { ReviewedPatchResult } from "../lib/reviewedClient";
import type { LabelsPatchResult } from "../lib/labelsClient";

export interface SegmentTableToast {
  level: "conflict" | "invalid" | "error" | "sync_warning";
  message: string;
}

export interface LabelsEditPayload {
  verb: string | null;
  object: string | null;
  target: string | null;
  failure_flags: string[];
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
  onLabelsEdit: (
    segmentId: string,
    labels: LabelsEditPayload,
  ) => Promise<LabelsPatchResult>;
  onEditFocus?: () => void;
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
    onLabelsEdit,
    onEditFocus,
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
            <th>verb</th>
            <th>object</th>
            <th>target</th>
            <th>flags</th>
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
              onLabelsEdit={onLabelsEdit}
              onEditFocus={onEditFocus}
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
  onLabelsEdit,
  onEditFocus,
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
  onLabelsEdit: (
    segmentId: string,
    labels: LabelsEditPayload,
  ) => Promise<LabelsPatchResult>;
  onEditFocus?: () => void;
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

  // Optimistic label fields: local text state, sync from props, blur-commit.
  const [localVerb, setLocalVerb] = useState(segment.verb ?? "");
  const [localObject, setLocalObject] = useState(segment.object ?? "");
  const [localTarget, setLocalTarget] = useState(segment.target ?? "");
  const [localFlags, setLocalFlags] = useState(
    segment.failure_flags.join(", "),
  );
  useEffect(() => {
    setLocalVerb(segment.verb ?? "");
  }, [segment.verb]);
  useEffect(() => {
    setLocalObject(segment.object ?? "");
  }, [segment.object]);
  useEffect(() => {
    setLocalTarget(segment.target ?? "");
  }, [segment.target]);
  useEffect(() => {
    setLocalFlags(segment.failure_flags.join(", "));
  }, [segment.failure_flags]);

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

  // Build the labels payload from current local state.
  const buildLabelsPayload = (
    verb: string,
    object_: string,
    target: string,
    flags: string,
  ): LabelsEditPayload => ({
    verb: verb.trim() || null,
    object: object_.trim() || null,
    target: target.trim() || null,
    failure_flags: flags.split(",").map((s) => s.trim()).filter(Boolean),
  });

  // Compare payload to current segment props to detect no-op on blur.
  const labelsChanged = (payload: LabelsEditPayload): boolean => {
    const currentFlags = list(segment.failure_flags);
    const newFlags = list(payload.failure_flags);
    return (
      payload.verb !== (segment.verb ?? null) ||
      payload.object !== (segment.object ?? null) ||
      payload.target !== (segment.target ?? null) ||
      JSON.stringify(currentFlags.slice().sort()) !==
        JSON.stringify(newFlags.slice().sort()) ||
      currentFlags.length !== newFlags.length
    );
  };

  // Helper to avoid importing a list utility for simple array comparison.
  function list<T>(arr: T[]): T[] { return arr; }

  const handleLabelBlur = async () => {
    const payload = buildLabelsPayload(localVerb, localObject, localTarget, localFlags);
    if (!labelsChanged(payload)) return;
    try {
      const r = await onLabelsEdit(segment.segment_id, payload);
      if (r.kind !== "ok") {
        // Rollback to segment prop values.
        setLocalVerb(segment.verb ?? "");
        setLocalObject(segment.object ?? "");
        setLocalTarget(segment.target ?? "");
        setLocalFlags(segment.failure_flags.join(", "));
      }
    } catch {
      setLocalVerb(segment.verb ?? "");
      setLocalObject(segment.object ?? "");
      setLocalTarget(segment.target ?? "");
      setLocalFlags(segment.failure_flags.join(", "));
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
            onFocus={onEditFocus}
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
            onFocus={onEditFocus}
            onChange={onReviewedChange}
          />
        ) : (
          <span>{segment.reviewed ? "✓" : "–"}</span>
        )}
      </td>
      <td>{segment.label_source}</td>
      <td>
        {editable ? (
          <input
            type="text"
            value={localVerb}
            disabled={disabled}
            aria-label={`verb for ${segment.segment_id}`}
            onFocus={onEditFocus}
            onChange={(e) => setLocalVerb(e.target.value)}
            onBlur={handleLabelBlur}
          />
        ) : (
          <span>{segment.verb ?? "–"}</span>
        )}
      </td>
      <td>
        {editable ? (
          <input
            type="text"
            value={localObject}
            disabled={disabled}
            aria-label={`object for ${segment.segment_id}`}
            onFocus={onEditFocus}
            onChange={(e) => setLocalObject(e.target.value)}
            onBlur={handleLabelBlur}
          />
        ) : (
          <span>{segment.object ?? "–"}</span>
        )}
      </td>
      <td>
        {editable ? (
          <input
            type="text"
            value={localTarget}
            disabled={disabled}
            aria-label={`target for ${segment.segment_id}`}
            onFocus={onEditFocus}
            onChange={(e) => setLocalTarget(e.target.value)}
            onBlur={handleLabelBlur}
          />
        ) : (
          <span>{segment.target ?? "–"}</span>
        )}
      </td>
      <td>
        {editable ? (
          <input
            type="text"
            value={localFlags}
            disabled={disabled}
            aria-label={`flags for ${segment.segment_id}`}
            onFocus={onEditFocus}
            onChange={(e) => setLocalFlags(e.target.value)}
            onBlur={handleLabelBlur}
          />
        ) : (
          <span>{segment.failure_flags.length > 0 ? segment.failure_flags.join(", ") : "–"}</span>
        )}
      </td>
    </tr>
  );
}
