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
  joints_2d: [number, number][] | null;
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
  depth_video_ready: boolean;
};

export type HandIndexDoc = {
  schema_version: string;
  episodes: HandEpisodeEntry[];
};

export type HandMetaDoc = {
  video_source: string;
  video_fps: number;
  video_total_frames: number;
  video_width?: number;
  video_height?: number;
  depth_source?: string;
  depth_meta?: {
    frames_processed?: number;
    frames_skipped_existing?: number;
    preset_params?: { fl_x_ref?: number; fl_y_ref?: number };
    ref_w_native?: number;
  };
  [key: string]: unknown;
};
