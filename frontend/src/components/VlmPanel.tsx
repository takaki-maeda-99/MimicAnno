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
  // Pair-index expansion: planner call_NNN ↔ labeler with segment_ordinal=NNN+1
  // share the same pair index (NNN). Clicking either row toggles the pair.
  const [expandedPair, setExpandedPair] = useState<number | null>(null);

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

  // Pair index: planner call_NNN → NNN; labeler ordinal K → K-1.
  const pairIndexOf = (c: VlmCall): number | null => {
    if (c.kind === "planner") {
      const m = c.call_id.match(/call_(\d+)/);
      return m ? parseInt(m[1], 10) : null;
    }
    return c.segment_ordinal !== null ? c.segment_ordinal - 1 : null;
  };

  const pairIndices = Array.from(
    new Set(
      calls
        .map(pairIndexOf)
        .filter((v): v is number => v !== null),
    ),
  ).sort((a, b) => a - b);

  const activePair = expandedPair ?? pairIndices[0] ?? null;
  const activeCalls =
    activePair === null
      ? []
      : calls.filter((c) => pairIndexOf(c) === activePair);

  return (
    <aside data-testid="vlm-panel">
      <section data-testid="vlm-input-section">
        <h4>VLM input</h4>
        <div data-testid="vlm-section-buttons" style={{ display: "flex", flexWrap: "wrap", gap: "4px", marginBottom: "8px" }}>
          {pairIndices.map((idx) => (
            <button
              key={idx}
              type="button"
              data-testid={`vlm-section-button-${idx}`}
              data-active={activePair === idx ? "true" : "false"}
              onClick={() => setExpandedPair(idx)}
              style={{
                fontWeight: activePair === idx ? "bold" : "normal",
              }}
            >
              section{idx + 1}
            </button>
          ))}
        </div>
        <div style={{ display: "flex", flexDirection: "row", gap: "8px", alignItems: "flex-start" }}>
          {activeCalls.map((c) => (
            <div key={c.call_id} style={{ flex: 1, minWidth: 0 }}>
              <CallRow
                call={c}
                selected={
                  c.kind === "labeler" &&
                  selectedOrdinal !== null &&
                  c.segment_ordinal === selectedOrdinal
                }
                expanded={true}
                onToggle={() => {}}
              />
            </div>
          ))}
        </div>
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
      </button>
      {expanded && call.kind === "labeler" && call.keyframe_urls.length > 0 ? (
        <div
          data-testid="vlm-keyframes"
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: "4px",
          }}
        >
          {call.keyframe_urls.map((url) => (
            <img
              key={url}
              src={url}
              alt="keyframe"
              style={{ width: "100%", display: "block" }}
            />
          ))}
        </div>
      ) : null}
      {expanded && call.kind === "planner" ? (
        <div data-testid={`vlm-expanded-${call.call_id}`}>
          <pre
            data-testid="vlm-prompt-full"
            style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", margin: 0 }}
          >
            {call.prompt}
          </pre>
          <pre
            data-testid="vlm-raw-output"
            style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", margin: 0 }}
          >
            {call.raw_output}
          </pre>
          <pre
            data-testid="vlm-parsed"
            style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", margin: 0 }}
          >
            {call.parsed === null
              ? "(unparseable)"
              : JSON.stringify(call.parsed, null, 2)}
          </pre>
        </div>
      ) : null}
    </div>
  );
}
