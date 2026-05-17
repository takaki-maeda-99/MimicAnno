import { type ReactNode, type MutableRefObject, useEffect, useRef } from "react";

type Props = {
  videoUrl: string;
  currentTimeSec: number;
  onTimeChange: (tSec: number) => void;
  onError: (message: string) => void;
  maskOverlay?: ReactNode;
  videoElRef?: MutableRefObject<HTMLVideoElement | null>;
};

export default function VideoPlayer({
  videoUrl,
  currentTimeSec,
  onTimeChange,
  onError,
  maskOverlay,
  videoElRef,
}: Props) {
  const ref = useRef<HTMLVideoElement | null>(null);
  useEffect(() => {
    if (videoElRef) videoElRef.current = ref.current;
  });

  useEffect(() => {
    const v = ref.current;
    if (!v) return;
    if (Math.abs(v.currentTime - currentTimeSec) > 0.05) {
      v.currentTime = currentTimeSec;
    }
  }, [currentTimeSec]);

  return (
    <div style={{ position: "relative", display: "inline-block", maxWidth: "100%" }}>
      <video
        ref={ref}
        src={videoUrl}
        controls
        onTimeUpdate={(e) => onTimeChange(e.currentTarget.currentTime)}
        onError={(e) => {
          const code = e.currentTarget.error?.code;
          onError(`video playback failed${code !== undefined ? ` (code ${code})` : ""}`);
        }}
        style={{ maxWidth: "100%", display: "block" }}
      />
      {maskOverlay}
    </div>
  );
}
