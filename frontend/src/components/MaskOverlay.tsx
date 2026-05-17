/**
 * U-A4 — SAM3 mask overlay canvas component.
 *
 * Renders an absolutely-positioned canvas on top of the video element
 * (injected via VideoPlayer's maskOverlay prop). On each frame change it
 * fetches the RGBA PNG from the backend (204 → clears canvas) and composites
 * it with the user-controlled alpha. Includes a per-track toggle legend.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import type { MasksMeta, MaskTrack } from "../lib/masksClient";
import { maskPngUrl } from "../lib/masksClient";

interface Props {
  apiBase: string;
  runName: string;
  runSet: string;
  currentFrame: number;
  meta: MasksMeta | null;
}

export default function MaskOverlay({
  apiBase,
  runName,
  runSet,
  currentFrame,
  meta,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [alpha, setAlpha] = useState(0.6);
  const [hidden, setHidden] = useState<Set<string>>(new Set());

  // Returns null (no overlay) when no sidecar or no frames.
  if (!meta || meta.frame_count === 0) return null;

  const tracks: MaskTrack[] = meta.tracks;

  // Debounced frame fetch: 100ms.
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const frameRef = useRef<number>(-1);

  const drawPng = useCallback(
    (blob: Blob, canvasEl: HTMLCanvasElement) => {
      const ctx = canvasEl.getContext("2d");
      if (!ctx) return;
      const url = URL.createObjectURL(blob);
      const img = new Image();
      img.onload = () => {
        canvasEl.width = img.naturalWidth;
        canvasEl.height = img.naturalHeight;
        ctx.clearRect(0, 0, canvasEl.width, canvasEl.height);
        ctx.globalAlpha = alpha;
        ctx.drawImage(img, 0, 0);
        ctx.globalAlpha = 1;
        URL.revokeObjectURL(url);
      };
      img.src = url;
    },
    [alpha],
  );

  const clearCanvas = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
  }, []);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      frameRef.current = currentFrame;
      const url = maskPngUrl(apiBase, runName, currentFrame, runSet);
      try {
        const r = await fetch(url);
        // If another frame was requested while we were waiting, discard.
        if (frameRef.current !== currentFrame) return;
        if (r.status === 204) {
          clearCanvas();
          return;
        }
        if (!r.ok) return;
        const blob = await r.blob();
        if (frameRef.current !== currentFrame) return;
        drawPng(blob, canvas);
      } catch {
        // Fetch aborted or network error — ignore.
      }
    }, 100);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [currentFrame, apiBase, runName, runSet, drawPng, clearCanvas]);

  // Re-draw when alpha changes (re-fetch current frame).
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const url = maskPngUrl(apiBase, runName, currentFrame, runSet);
    fetch(url)
      .then(async (r) => {
        if (r.status === 204) { clearCanvas(); return; }
        if (!r.ok) return;
        const blob = await r.blob();
        drawPng(blob, canvas);
      })
      .catch(() => undefined);
  }, [alpha]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggleTrack = (trackId: string) => {
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(trackId)) next.delete(trackId);
      else next.add(trackId);
      return next;
    });
  };

  return (
    <>
      {/* Canvas overlaid on video — pointer-events:none so video controls work */}
      <canvas
        ref={canvasRef}
        data-testid="mask-overlay-canvas"
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          width: "100%",
          height: "100%",
          pointerEvents: "none",
          opacity: hidden.size === tracks.length ? 0 : 1,
        }}
      />

      {/* Controls panel below canvas (inside the relative wrapper from VideoPlayer) */}
      <div
        data-testid="mask-overlay-controls"
        style={{
          position: "absolute",
          bottom: 8,
          left: 8,
          background: "rgba(0,0,0,0.55)",
          borderRadius: 4,
          padding: "4px 8px",
          color: "#fff",
          fontSize: 12,
          display: "flex",
          flexDirection: "column",
          gap: 4,
          pointerEvents: "auto",
        }}
      >
        <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span>Mask alpha</span>
          <input
            data-testid="mask-alpha-slider"
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={alpha}
            onChange={(e) => setAlpha(parseFloat(e.currentTarget.value))}
            style={{ width: 80 }}
          />
          <span>{Math.round(alpha * 100)}%</span>
        </label>

        {/* Per-track color swatches + toggles */}
        {tracks.map((t) => (
          <label
            key={t.track_id}
            style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}
          >
            <span
              data-testid={`mask-color-swatch-${t.track_id}`}
              style={{
                display: "inline-block",
                width: 12,
                height: 12,
                background: t.color,
                border: "1px solid rgba(255,255,255,0.4)",
                borderRadius: 2,
              }}
            />
            <input
              data-testid={`mask-track-toggle-${t.track_id}`}
              type="checkbox"
              checked={!hidden.has(t.track_id)}
              onChange={() => toggleTrack(t.track_id)}
            />
            <span style={{ opacity: hidden.has(t.track_id) ? 0.4 : 1 }}>
              {t.prompt}
            </span>
          </label>
        ))}
      </div>
    </>
  );
}
