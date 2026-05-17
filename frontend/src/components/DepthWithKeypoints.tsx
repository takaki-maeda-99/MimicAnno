import { useEffect, useRef, useState } from "react";
import type { HandSignalFrame } from "../lib/handsClient";
import { drawHandSkeleton } from "../lib/handSkeleton";

const RIGHT_COLOR = "rgb(0, 220, 60)";
const LEFT_COLOR = "rgb(255, 140, 0)";

export default function DepthWithKeypoints({
  videoUrl,
  currentTimeSec,
  onTimeChange,
  onError,
  videoWidth,
  videoHeight,
  rightHand,
  leftHand,
  videoElRef,
}: {
  videoUrl: string;
  currentTimeSec: number;
  onTimeChange: (t: number) => void;
  onError: (msg: string) => void;
  videoWidth: number;
  videoHeight: number;
  rightHand: HandSignalFrame | null;
  leftHand: HandSignalFrame | null;
  videoElRef?: React.MutableRefObject<HTMLVideoElement | null>;
}) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  useEffect(() => {
    if (videoElRef) videoElRef.current = videoRef.current;
  });
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
    const draws: [HandSignalFrame | null, string][] = [
      [rightHand, RIGHT_COLOR],
      [leftHand, LEFT_COLOR],
    ];
    for (const [hand, color] of draws) {
      if (!hand || !hand.joints_2d) continue;
      drawHandSkeleton({
        ctx,
        joints2d: hand.joints_2d,
        scaleX,
        scaleY,
        color,
        alpha: hand.depth_ok ? 0.95 : 0.6,
      });
    }
  }, [displayed, rightHand, leftHand, videoWidth, videoHeight]);

  return (
    <div style={{ position: "relative", display: "inline-block", width: "100%" }}>
      <video
        ref={videoRef}
        src={videoUrl}
        controls
        style={{ display: "block", width: "100%", maxWidth: "100%" }}
        onTimeUpdate={(e) => onTimeChange(e.currentTarget.currentTime)}
        onLoadedMetadata={(e) => {
          setDisplayed({ w: e.currentTarget.clientWidth, h: e.currentTarget.clientHeight });
        }}
        onError={(e) => {
          const code = e.currentTarget.error?.code;
          onError(`depth video playback failed${code !== undefined ? ` (code ${code})` : ""}`);
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
