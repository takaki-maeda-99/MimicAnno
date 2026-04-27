import { useEffect, useRef } from "react";

type Props = {
  videoUrl: string;
  currentTimeSec: number;
  onTimeChange: (tSec: number) => void;
  onError: (message: string) => void;
};

export default function VideoPlayer({ videoUrl, currentTimeSec, onTimeChange, onError }: Props) {
  const ref = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    const v = ref.current;
    if (!v) return;
    if (Math.abs(v.currentTime - currentTimeSec) > 0.05) {
      v.currentTime = currentTimeSec;
    }
  }, [currentTimeSec]);

  return (
    <video
      ref={ref}
      src={videoUrl}
      controls
      onTimeUpdate={(e) => onTimeChange(e.currentTarget.currentTime)}
      onError={(e) => {
        const code = e.currentTarget.error?.code;
        onError(`video playback failed${code !== undefined ? ` (code ${code})` : ""}`);
      }}
      style={{ maxWidth: "100%" }}
    />
  );
}
