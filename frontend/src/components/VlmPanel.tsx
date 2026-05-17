/** U-A3 — RunViewer right-panel "VLM" tab (master §2.4 rev3).
 *
 *  Read-only viewer of `_vlm_dumps/` planner + labeler calls for the
 *  currently selected canonical run. Highlights labeler rows whose
 *  segment_ordinal matches the currently selected segment in SegmentTable.
 */
import { useEffect, useState } from "react";
import { fetchVlmDumps, type VlmCall, type VlmDumps } from "../lib/vlmClient";

export interface VlmPanelProps {
  apiBase: string;
  canonical: string | null;
  runSet: string | null;
  /** String segment ID from SegmentTable e.g. "s_001" — null if none. */
  selectedSegmentId: string | null;
}

type State =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ok"; data: VlmDumps };

/** Parse "s_NNN" → integer ordinal, or null on malformed input. */
function ordinalFromSegmentId(segId: string | null): number | null {
  if (!segId || !segId.startsWith("s_")) return null;
  const n = parseInt(segId.slice(2), 10);
  return isNaN(n) ? null : n;
}

export default function VlmPanel(props: VlmPanelProps): React.JSX.Element {
  const { apiBase, canonical, runSet, selectedSegmentId } = props;
  const [state, setState] = useState<State>({ kind: "idle" });
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    if (!canonical || !runSet) {
      setState({ kind: "idle" });
      return;
    }
    const ctrl = new AbortController();
    setState({ kind: "loading" });
    fetchVlmDumps({ apiBase, canonical, runSet, signal: ctrl.signal })
      .then((data) => setState({ kind: "ok", data }))
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        const message = err instanceof Error ? err.message : String(err);
        setState({ kind: "error", message });
      });
    return () => ctrl.abort();
  }, [apiBase, canonical, runSet]);

  if (state.kind === "idle") {
    return <aside data-testid="vlm-panel" />;
  }
  if (state.kind === "loading") {
    return (
      <aside data-testid="vlm-panel">
        <p>Loading VLM dumps…</p>
      </aside>
    );
  }
  if (state.kind === "error") {
    return (
      <aside data-testid="vlm-panel">
        <p role="alert">VLM dumps error: {state.message}</p>
      </aside>
    );
  }

  const { calls } = state.data;
  if (calls.length === 0) {
    return (
      <aside data-testid="vlm-panel">
        <p>No VLM dumps for this episode</p>
      </aside>
    );
  }

  const selectedOrdinal = ordinalFromSegmentId(selectedSegmentId);
  const plannerRows = calls.filter((c) => c.kind === "planner");
  const labelerRows = calls.filter((c) => c.kind === "labeler");

  return (
    <aside data-testid="vlm-panel">
      {plannerRows.length > 0 ? (
        <section data-testid="vlm-planner-section">
          <h4>Planner</h4>
          {plannerRows.map((c) => (
            <CallRow
              key={c.call_id}
              call={c}
              selected={false}
              expanded={expanded === c.call_id}
              onToggle={() =>
                setExpanded((cur) => (cur === c.call_id ? null : c.call_id))
              }
            />
          ))}
        </section>
      ) : null}
      <section data-testid="vlm-segments-section">
        <h4>Segments</h4>
        {labelerRows.map((c) => (
          <CallRow
            key={c.call_id}
            call={c}
            selected={
              selectedOrdinal !== null &&
              c.segment_ordinal === selectedOrdinal
            }
            expanded={expanded === c.call_id}
            onToggle={() =>
              setExpanded((cur) => (cur === c.call_id ? null : c.call_id))
            }
          />
        ))}
      </section>
    </aside>
  );
}

function CallRow(props: {
  call: VlmCall;
  selected: boolean;
  expanded: boolean;
  onToggle: () => void;
}): React.JSX.Element {
  const { call, selected, expanded, onToggle } = props;
  const classes: string[] = ["vlm-call-row"];
  if (selected) classes.push("is-selected");
  if (call.failed) classes.push("is-failed");

  // Summary line: for labeler show ordinal; for planner show call_id
  const summaryLabel =
    call.kind === "labeler"
      ? `s_${String(call.segment_ordinal ?? "?").padStart(3, "0")} attempt_${call.attempt ?? "?"}`
      : call.call_id;

  return (
    <div
      className={classes.join(" ")}
      data-testid={`vlm-call-${call.call_id}`}
      data-selected={selected ? "true" : "false"}
      data-failed={call.failed ? "true" : "false"}
    >
      <button type="button" onClick={onToggle}>
        <span data-testid="vlm-kind-badge">{call.kind}</span>
        <span>{summaryLabel}</span>
        <span>{call.prompt.slice(0, 80)}</span>
      </button>
      {call.kind === "planner" && call.frame_url ? (
        <img
          data-testid="vlm-planner-frame"
          src={call.frame_url}
          alt="planner frame"
          style={{ maxWidth: "100%", display: "block" }}
        />
      ) : null}
      {expanded ? (
        <div data-testid={`vlm-expanded-${call.call_id}`}>
          {call.kind === "labeler" && call.keyframe_urls.length > 0 ? (
            <div data-testid="vlm-keyframes">
              {call.keyframe_urls.map((url) => (
                <img
                  key={url}
                  src={url}
                  alt="keyframe"
                  style={{ maxWidth: "120px", marginRight: "4px" }}
                />
              ))}
            </div>
          ) : null}
          <pre data-testid="vlm-prompt-full">{call.prompt}</pre>
          {call.request_json !== null ? (
            <pre data-testid="vlm-request-json">
              {JSON.stringify(call.request_json, null, 2)}
            </pre>
          ) : null}
          <pre data-testid="vlm-raw-output">{call.raw_output}</pre>
          <pre data-testid="vlm-parsed">
            {call.parsed === null
              ? "(unparseable)"
              : JSON.stringify(call.parsed, null, 2)}
          </pre>
        </div>
      ) : null}
    </div>
  );
}
