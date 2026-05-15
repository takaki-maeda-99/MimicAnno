/**
 * Types for the /api/hands/ backend.
 *
 * HandViewer intentionally bypasses useApiToggle() — there is no static
 * fallback for hand data, so the base URL is always /api/hands/.
 */

export type HandSignalFrame = {
  pinch_m: number | null;
  cam_t: [number, number, number];
  euler_deg: { yaw: number; pitch: number; roll: number };
  depth_ok: boolean;
};

export type HandFrameEntry = {
  right: HandSignalFrame | null;
  left: HandSignalFrame | null;
};

export type HandSignalsDoc = {
  schema_version: number;
  [frame_key: string]: HandFrameEntry | number;
};

export type HandEpisodeEntry = {
  episode_id: string;
  signals_ready: boolean;
};

export type HandIndexDoc = {
  schema_version: string;
  episodes: HandEpisodeEntry[];
};

export type HandMetaDoc = {
  video_source: string;
  video_fps: number;
  video_total_frames: number;
  [key: string]: unknown;
};
