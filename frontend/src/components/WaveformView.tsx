import type { SignalChannel } from "../lib/manifest";

const CHANNEL_HEIGHT_PX = 60;

type Props = {
  widthPx: number;
  durationSec: number;
  currentTimeSec: number;
  channels: SignalChannel[];
};

export default function WaveformView({ widthPx, durationSec, currentTimeSec, channels }: Props) {
  if (widthPx === 0 || durationSec <= 0) return null;
  return (
    <div className="waveform-view">
      {channels.map((ch) => (
        <ChannelRow
          key={ch.name}
          channel={ch}
          widthPx={widthPx}
          durationSec={durationSec}
          currentTimeSec={currentTimeSec}
        />
      ))}
    </div>
  );
}

function ChannelRow({
  channel,
  widthPx,
  durationSec,
  currentTimeSec,
}: {
  channel: SignalChannel;
  widthPx: number;
  durationSec: number;
  currentTimeSec: number;
}) {
  if (channel.values.length === 0) return null;
  let min = Infinity, max = -Infinity;
  for (const v of channel.values) {
    if (v < min) min = v;
    if (v > max) max = v;
  }
  const range = max - min || 1;
  const scaleX = (t: number) => (t / durationSec) * widthPx;
  const scaleY = (v: number) =>
    CHANNEL_HEIGHT_PX - 4 - ((v - min) / range) * (CHANNEL_HEIGHT_PX - 8);
  const points = channel.values
    .map((v, i) => {
      const t = channel.t0_sec + i * channel.dt_sec;
      return `${scaleX(t).toFixed(2)},${scaleY(v).toFixed(2)}`;
    })
    .join(" ");
  return (
    <div className="waveform-row">
      <div className="waveform-label">
        {channel.name} <span className="waveform-unit">[{channel.unit}]</span>
      </div>
      <svg width={widthPx} height={CHANNEL_HEIGHT_PX} style={{ background: "#fafafa", display: "block" }}>
        <polyline fill="none" stroke="#111" strokeWidth={1} points={points} />
        <line
          x1={scaleX(currentTimeSec)}
          x2={scaleX(currentTimeSec)}
          y1={0}
          y2={CHANNEL_HEIGHT_PX}
          stroke="#111"
          strokeWidth={1}
          opacity={0.5}
          pointerEvents="none"
        />
      </svg>
    </div>
  );
}
