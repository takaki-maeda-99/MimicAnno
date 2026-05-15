import { useCallback, useEffect, useRef, useState } from "react";
import type {
  HandIndexDoc,
  HandMetaDoc,
  HandSignalFrame,
  HandSignalsDoc,
} from "../lib/handsClient";
import { projectHandAxes, drawAxes } from "../lib/handAxes";
import HandScrubBar from "./HandScrubBar";
import HandSignalGraph from "./HandSignalGraph";

const AXIS_LENGTH_M = 0.05;

function VideoWithAxes({
  videoUrl,
  currentTimeSec,
  onTimeChange,
  onError,
  videoWidth,
  videoHeight,
  intrinsics,
  rightHand,
  leftHand,
}: {
  videoUrl: string;
  currentTimeSec: number;
  onTimeChange: (t: number) => void;
  onError: (msg: string) => void;
  videoWidth: number;
  videoHeight: number;
  intrinsics?: { fx: number; fy: number; cx: number; cy: number };
  rightHand: HandSignalFrame | null;
  leftHand: HandSignalFrame | null;
}) {
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [displayed, setDisplayed] = useState<{ w: number; h: number }>({ w: 0, h: 0 });

  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    if (Math.abs(v.currentTime - currentTimeSec) > 0.05) v.currentTime = currentTimeSec;
  }, [currentTimeSec]);

  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    setDisplayed({ w: v.clientWidth, h: v.clientHeight });
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => {
      setDisplayed({ w: v.clientWidth, h: v.clientHeight });
    });
    ro.observe(v);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = displayed.w * dpr;
    canvas.height = displayed.h * dpr;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, displayed.w, displayed.h);
    if (videoWidth <= 0 || videoHeight <= 0 || displayed.w <= 0) return;
    const scaleX = displayed.w / videoWidth;
    const scaleY = displayed.h / videoHeight;
    for (const hand of [rightHand, leftHand]) {
      if (!hand) continue;
      const proj = projectHandAxes({
        cam_t: hand.cam_t,
        euler_deg: hand.euler_deg,
        axisLengthM: AXIS_LENGTH_M,
        videoWidth,
        videoHeight,
        intrinsics,
      });
      if (!proj) continue;
      drawAxes({ ctx, proj, scaleX, scaleY, lineWidth: 3, alpha: hand.depth_ok ? 0.95 : 0.6 });
    }
  }, [displayed, rightHand, leftHand, videoWidth, videoHeight, intrinsics]);

  return (
    <div ref={wrapRef} style={{ position: "relative", display: "inline-block" }}>
      <video
        ref={videoRef}
        src={videoUrl}
        controls
        style={{ display: "block", maxWidth: "100%" }}
        onTimeUpdate={(e) => onTimeChange(e.currentTarget.currentTime)}
        onLoadedMetadata={(e) => {
          setDisplayed({ w: e.currentTarget.clientWidth, h: e.currentTarget.clientHeight });
        }}
        onError={(e) => {
          const code = e.currentTarget.error?.code;
          onError(`video playback failed${code !== undefined ? ` (code ${code})` : ""}`);
        }}
      />
      <canvas
        ref={canvasRef}
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          width: displayed.w,
          height: displayed.h,
          pointerEvents: "none",
        }}
      />
    </div>
  );
}

// /api/hands/ is hardcoded — there is no static fallback for hand data.
// This is an intentional divergence from the RunViewer pattern (useApiToggle).
const HANDS_API_BASE = "/api/hands/";

function formatTime(sec: number): string {
  const mm = Math.floor(sec / 60).toString().padStart(2, "0");
  const ss = (sec % 60).toFixed(1).padStart(4, "0");
  return `${mm}:${ss}`;
}

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
  const [widthPx, setWidthPx] = useState(0);
  const obsRef = useRef<ResizeObserver | null>(null);
  const rowRef = useCallback((node: HTMLDivElement | null) => {
    obsRef.current?.disconnect();
    obsRef.current = null;
    if (node) {
      if (typeof ResizeObserver === "undefined") return;
      const obs = new ResizeObserver((entries) => {
        const w = entries[0]?.contentRect.width ?? 0;
        if (w > 0) setWidthPx(w);
      });
      obs.observe(node);
      obsRef.current = obs;
    }
  }, []);

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
  const frameEntry = signals[frameKey] as
    | { right: HandSignalFrame | null; left: HandSignalFrame | null }
    | undefined;
  const rightHand = frameEntry?.right ?? null;
  const leftHand = frameEntry?.left ?? null;
  const videoW = (meta.video_width as number | undefined) ?? 0;
  const videoH = (meta.video_height as number | undefined) ?? 0;
  // Extract real camera intrinsics from depth_meta if available (OpenCV
  // fisheye with k1..k4 = 0 reduces to a pinhole; we ignore distortion).
  const depthMeta = meta.depth_meta as { preset_params?: { fl_x_ref?: number; fl_y_ref?: number }; ref_w_native?: number } | undefined;
  const refW = depthMeta?.ref_w_native ?? 5312;
  const flXRef = depthMeta?.preset_params?.fl_x_ref;
  const flYRef = depthMeta?.preset_params?.fl_y_ref;
  const intrinsics =
    flXRef !== undefined && flYRef !== undefined && videoW > 0
      ? {
          fx: (flXRef * videoW) / refW,
          fy: (flYRef * videoW) / refW,
          cx: videoW / 2,
          cy: videoH / 2,
        }
      : undefined;

  return (
    <div className="hand-viewer">
      <div className="back-link">
        <a href="/">← runs</a>
      </div>
      <div className="hand-viewer-layout">
        <div className="hand-viewer-video" ref={rowRef}>
          <VideoWithAxes
            videoUrl={`${HANDS_API_BASE}${episodeId}/video`}
            currentTimeSec={currentTimeSec}
            onTimeChange={setCurrentTimeSec}
            onError={setVideoError}
            videoWidth={videoW}
            videoHeight={videoH}
            intrinsics={intrinsics}
            rightHand={rightHand}
            leftHand={leftHand}
          />
          {videoError && <div className="error">{videoError}</div>}
          <HandScrubBar
            widthPx={widthPx}
            totalFrames={totalFrames}
            currentFrame={currentFrame}
            onSeek={(f) => fps > 0 && setCurrentTimeSec(f / fps)}
          />
          <div className="hand-scrub-info">
            frame {currentFrame} / {totalFrames - 1}{"  |  "}{formatTime(currentTimeSec)}
          </div>
          <HandSignalGraph
            signals={signals}
            side="right"
            widthPx={widthPx}
            totalFrames={totalFrames}
            currentFrame={currentFrame}
            onSeek={(f) => fps > 0 && setCurrentTimeSec(f / fps)}
          />
          <HandSignalGraph
            signals={signals}
            side="left"
            widthPx={widthPx}
            totalFrames={totalFrames}
            currentFrame={currentFrame}
            onSeek={(f) => fps > 0 && setCurrentTimeSec(f / fps)}
          />
        </div>
        <div className="hand-viewer-data">
          <HandDataPanel frameKey={frameKey} signals={signals} />
        </div>
      </div>
    </div>
  );
}
