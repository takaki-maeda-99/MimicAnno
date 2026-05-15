import { useEffect, useState } from "react";
import type {
  HandIndexDoc,
  HandMetaDoc,
  HandSignalFrame,
  HandSignalsDoc,
} from "../lib/handsClient";
import VideoPlayer from "./VideoPlayer";

// /api/hands/ is hardcoded — there is no static fallback for hand data.
// This is an intentional divergence from the RunViewer pattern (useApiToggle).
const HANDS_API_BASE = "/api/hands/";

type LoadedState = {
  meta: HandMetaDoc;
  signals: HandSignalsDoc;
};

type State =
  | { kind: "loading" }
  | { kind: "unavailable" }
  | { kind: "no-episode"; episodeId: string }
  | { kind: "signals-not-ready"; episodeId: string }
  | { kind: "signals-bad-version" }
  | { kind: "error"; message: string }
  | { kind: "loaded"; data: LoadedState };

type Props = { episodeId: string };

function HandDataPanel({
  frameKey,
  signals,
}: {
  frameKey: string;
  signals: HandSignalsDoc;
}) {
  const entry = signals[frameKey] as
    | { right: HandSignalFrame | null; left: HandSignalFrame | null }
    | undefined;
  if (entry === undefined) {
    return <div className="hand-data-panel">フレームデータなし</div>;
  }

  function HandSide({
    label,
    hand,
  }: {
    label: string;
    hand: HandSignalFrame | null;
  }) {
    if (hand === null) {
      return (
        <div className="hand-side">
          <strong>{label}</strong>: <span className="hand-undetected">未検出</span>
        </div>
      );
    }
    const dimClass = hand.depth_ok ? "" : "hand-estimated";
    const badge = hand.depth_ok ? null : <span className="hand-badge">(推定)</span>;
    return (
      <div className="hand-side">
        <strong>{label}</strong>
        {badge}
        <table className={dimClass}>
          <tbody>
            <tr>
              <td>cam_t</td>
              <td>[{hand.cam_t.map((v) => v.toFixed(3)).join(", ")}]</td>
            </tr>
            <tr>
              <td>yaw / pitch / roll</td>
              <td>
                {hand.euler_deg.yaw.toFixed(1)}° / {hand.euler_deg.pitch.toFixed(1)}° /{" "}
                {hand.euler_deg.roll.toFixed(1)}°
              </td>
            </tr>
            <tr>
              <td>pinch</td>
              <td>
                {hand.pinch_m !== null
                  ? `${(hand.pinch_m * 1000).toFixed(1)} mm`
                  : "—"}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <div className="hand-data-panel">
      <HandSide label="右手" hand={entry.right} />
      <HandSide label="左手" hand={entry.left} />
    </div>
  );
}

export default function HandViewer({ episodeId }: Props) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [currentTimeSec, setCurrentTimeSec] = useState(0);
  const [videoError, setVideoError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setState({ kind: "loading" });
    setCurrentTimeSec(0);

    (async () => {
      let indexDoc: HandIndexDoc;
      try {
        const r = await fetch(`${HANDS_API_BASE}index.json`);
        if (r.status === 503) {
          if (!cancelled) setState({ kind: "unavailable" });
          return;
        }
        if (!r.ok) {
          if (!cancelled)
            setState({ kind: "error", message: `index.json: HTTP ${r.status}` });
          return;
        }
        indexDoc = (await r.json()) as HandIndexDoc;
      } catch {
        if (!cancelled) setState({ kind: "unavailable" });
        return;
      }

      const epEntry = indexDoc.episodes.find((e) => e.episode_id === episodeId);
      if (!epEntry) {
        if (!cancelled) setState({ kind: "no-episode", episodeId });
        return;
      }
      if (!epEntry.signals_ready) {
        if (!cancelled) setState({ kind: "signals-not-ready", episodeId });
        return;
      }

      try {
        const [metaR, sigR] = await Promise.all([
          fetch(`${HANDS_API_BASE}${episodeId}/meta.json`),
          fetch(`${HANDS_API_BASE}${episodeId}/signals.json`),
        ]);
        if (!metaR.ok || !sigR.ok) {
          if (!cancelled)
            setState({
              kind: "error",
              message: `fetch failed: meta=${metaR.status} signals=${sigR.status}`,
            });
          return;
        }
        const meta = (await metaR.json()) as HandMetaDoc;
        const signals = (await sigR.json()) as HandSignalsDoc;

        if (signals.schema_version !== 2) {
          if (!cancelled) setState({ kind: "signals-bad-version" });
          return;
        }

        if (!cancelled) setState({ kind: "loaded", data: { meta, signals } });
      } catch (err) {
        if (!cancelled)
          setState({
            kind: "error",
            message: err instanceof Error ? err.message : String(err),
          });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [episodeId]);

  if (state.kind === "loading") return <div>loading…</div>;
  if (state.kind === "unavailable") return <div>手のデータがありません</div>;
  if (state.kind === "no-episode")
    return <div>エピソードが見つかりません: {state.episodeId}</div>;
  if (state.kind === "signals-not-ready")
    return <div>このエピソードは signals.json が未生成です: {state.episodeId}</div>;
  if (state.kind === "signals-bad-version")
    return (
      <div>
        signals.json が古いフォーマットです。--signals-only --full-signals で再生成してください
      </div>
    );
  if (state.kind === "error") return <div className="error">{state.message}</div>;

  const { meta, signals } = state.data;
  const fps = meta.video_fps;
  const totalFrames = meta.video_total_frames;
  const currentFrame = Math.min(
    Math.round(currentTimeSec * fps),
    totalFrames - 1,
  );
  const frameKey = `frame_${String(currentFrame).padStart(6, "0")}`;

  return (
    <div className="hand-viewer">
      <h1>hand viewer — {episodeId}</h1>
      <a href="/">← 戻る</a>
      <div className="hand-viewer-layout">
        <div className="hand-viewer-video">
          <VideoPlayer
            videoUrl={`${HANDS_API_BASE}${episodeId}/video`}
            currentTimeSec={currentTimeSec}
            onTimeChange={setCurrentTimeSec}
            onError={setVideoError}
          />
          {videoError && <div className="error">{videoError}</div>}
          <div>frame: {currentFrame} / {totalFrames - 1}</div>
        </div>
        <div className="hand-viewer-data">
          <HandDataPanel frameKey={frameKey} signals={signals} />
        </div>
      </div>
    </div>
  );
}
