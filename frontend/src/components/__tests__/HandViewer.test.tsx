import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import HandViewer from "../HandViewer";

const META = {
  video_source: "tests/server/fixtures/hands/GX010085/video.mp4",
  video_fps: 30.0,
  video_total_frames: 3,
  video_width: 16,
  video_height: 16,
};

const DUMMY_JOINTS_2D = Array.from({ length: 21 }, (_, i) => [i, 0]);

const SIGNALS: Record<string, unknown> = {
  schema_version: 3,
  frame_000000: {
    right: {
      pinch_m: 0.034,
      cam_t: [0.12, -0.05, 0.63],
      euler_deg: { yaw: 45.6, pitch: -8.1, roll: 12.3 },
      depth_ok: true,
      joints_2d: DUMMY_JOINTS_2D,
    },
    left: null,
  },
  frame_000001: { right: null, left: null },
  frame_000002: {
    right: {
      pinch_m: 0.02,
      cam_t: [0.1, 0.0, 0.5],
      euler_deg: { yaw: 10.0, pitch: 5.0, roll: -3.0 },
      depth_ok: false,
      joints_2d: DUMMY_JOINTS_2D,
    },
    left: null,
  },
};

const INDEX = {
  schema_version: "0.1.0",
  episodes: [
    { episode_id: "GX010085", signals_ready: true, depth_video_ready: true },
    { episode_id: "GX010086", signals_ready: false },
  ],
};

function jsonResp(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function defaultFetch() {
  return vi.fn(async (url: string) => {
    if (url.endsWith("/index.json")) return jsonResp(INDEX);
    if (url.endsWith("/meta.json")) return jsonResp(META);
    if (url.endsWith("/signals.json")) return jsonResp(SIGNALS);
    return new Response("not found", { status: 404 });
  });
}

beforeEach(() => {
  vi.spyOn(window, "fetch").mockImplementation(defaultFetch() as typeof fetch);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("frame index calculation", () => {
  it("fps=30 currentTime=0 → frame 0 data shown", async () => {
    render(<HandViewer episodeId="GX010085" />);
    await waitFor(() => expect(screen.queryByText(/loading/)).toBeNull());
    expect(screen.getByText(/34\.0 mm/)).toBeTruthy();
  });

  it("clamps currentTime beyond total_frames to last frame", async () => {
    render(<HandViewer episodeId="GX010085" />);
    await waitFor(() => expect(screen.queryByText(/loading/)).toBeNull());
    expect(screen.getByText(/frame 0 \/ 2/)).toBeTruthy();
  });
});

it("depth_ok=false shows 推定 badge", async () => {
  const falseDepthSignals = {
    schema_version: 3,
    frame_000000: {
      right: {
        pinch_m: 0.02,
        cam_t: [0.1, 0.0, 0.5],
        euler_deg: { yaw: 10.0, pitch: 5.0, roll: -3.0 },
        depth_ok: false,
        joints_2d: DUMMY_JOINTS_2D,
      },
      left: null,
    },
  };
  vi.spyOn(window, "fetch").mockImplementation(
    vi.fn(async (url: string) => {
      if (url.endsWith("/index.json")) return jsonResp(INDEX);
      if (url.endsWith("/meta.json")) return jsonResp({ ...META, video_total_frames: 1 });
      if (url.endsWith("/signals.json")) return jsonResp(falseDepthSignals);
      return new Response("not found", { status: 404 });
    }) as typeof fetch,
  );
  render(<HandViewer episodeId="GX010085" />);
  await waitFor(() => expect(screen.queryByText(/loading/)).toBeNull());
  expect(screen.getByText("(推定)")).toBeTruthy();
  const estimatedEls = document.querySelectorAll(".hand-estimated");
  expect(estimatedEls.length).toBeGreaterThan(0);
});

it("schema_version≠3 (e.g. 1) shows re-generate message", async () => {
  vi.spyOn(window, "fetch").mockImplementation(
    vi.fn(async (url: string) => {
      if (url.endsWith("/index.json")) return jsonResp(INDEX);
      if (url.endsWith("/meta.json")) return jsonResp(META);
      if (url.endsWith("/signals.json")) return jsonResp({ schema_version: 1 });
      return new Response("not found", { status: 404 });
    }) as typeof fetch,
  );
  render(<HandViewer episodeId="GX010085" />);
  await waitFor(() => screen.getByText(/signals.json が古いフォーマット/));
});

it("schema_version=2 also shows re-generate message", async () => {
  vi.spyOn(window, "fetch").mockImplementation(
    vi.fn(async (url: string) => {
      if (url.endsWith("/index.json")) return jsonResp(INDEX);
      if (url.endsWith("/meta.json")) return jsonResp(META);
      if (url.endsWith("/signals.json")) return jsonResp({ schema_version: 2 });
      return new Response("not found", { status: 404 });
    }) as typeof fetch,
  );
  render(<HandViewer episodeId="GX010085" />);
  await waitFor(() => screen.getByText(/signals.json が古いフォーマット/));
});

it("503 on index.json shows 手のデータがありません", async () => {
  vi.spyOn(window, "fetch").mockImplementation(
    vi.fn(async () => new Response("{}", { status: 503 })) as typeof fetch,
  );
  render(<HandViewer episodeId="GX010085" />);
  await waitFor(() => screen.getByText(/手のデータがありません/));
});

it("network error on index.json shows 手のデータがありません", async () => {
  vi.spyOn(window, "fetch").mockImplementation(
    vi.fn().mockRejectedValue(new TypeError("network fail")) as typeof fetch,
  );
  render(<HandViewer episodeId="GX010085" />);
  await waitFor(() => screen.getByText(/手のデータがありません/));
});

it("episodeId not in index shows エピソードが見つかりません", async () => {
  render(<HandViewer episodeId="UNKNOWN_EP" />);
  await waitFor(() => screen.getByText(/エピソードが見つかりません: UNKNOWN_EP/));
});

it("signals_ready=false shows 未生成 message", async () => {
  render(<HandViewer episodeId="GX010086" />);
  await waitFor(() => screen.getByText(/signals.json が未生成/));
});

it("null frame entry shows 未検出 for both hands", async () => {
  const nullSignals = {
    schema_version: 3,
    frame_000000: { right: null, left: null },
  };
  vi.spyOn(window, "fetch").mockImplementation(
    vi.fn(async (url: string) => {
      if (url.endsWith("/index.json")) return jsonResp(INDEX);
      if (url.endsWith("/meta.json")) return jsonResp({ ...META, video_total_frames: 1 });
      if (url.endsWith("/signals.json")) return jsonResp(nullSignals);
      return new Response("not found", { status: 404 });
    }) as typeof fetch,
  );
  render(<HandViewer episodeId="GX010085" />);
  await waitFor(() => expect(screen.queryByText(/loading/)).toBeNull());
  const undetectedEls = screen.getAllByText("未検出");
  expect(undetectedEls.length).toBe(2);
});

it("HandViewer owns currentTimeSec: onTimeChange updates frame display", async () => {
  render(<HandViewer episodeId="GX010085" />);
  await waitFor(() => expect(screen.queryByText(/loading/)).toBeNull());
  expect(screen.getByText(/frame 0 \/ 2/)).toBeTruthy();

  const video = document.querySelector("video");
  expect(video).not.toBeNull();
  await act(async () => {
    Object.defineProperty(video, "currentTime", { value: 1.0, writable: true });
    video!.dispatchEvent(new Event("timeupdate"));
  });
  // frame = round(1.0 * 30) = 30, clamped to total_frames-1 = 2
  await waitFor(() => screen.getByText(/frame 2 \/ 2/));
});

describe("HandViewer layout improvements", () => {
  it("back-link is '← runs' with href='/'", async () => {
    render(<HandViewer episodeId="GX010085" />);
    await waitFor(() => expect(screen.queryByText(/loading/)).toBeNull());
    const link = screen.getByRole("link", { name: "← runs" });
    expect(link).toBeTruthy();
    expect(link.getAttribute("href")).toBe("/");
  });

  it("h1 heading does not exist", async () => {
    render(<HandViewer episodeId="GX010085" />);
    await waitFor(() => expect(screen.queryByText(/loading/)).toBeNull());
    expect(screen.queryByRole("heading", { level: 1 })).toBeNull();
  });

  it(".hand-viewer-layout exists", async () => {
    render(<HandViewer episodeId="GX010085" />);
    await waitFor(() => expect(screen.queryByText(/loading/)).toBeNull());
    expect(document.querySelector(".hand-viewer-layout")).not.toBeNull();
  });

  it("scrub-info shows frame number", async () => {
    render(<HandViewer episodeId="GX010085" />);
    await waitFor(() => expect(screen.queryByText(/loading/)).toBeNull());
    expect(screen.getByText(/frame 0 \/ 2/)).toBeTruthy();
  });

  it("scrub-info shows time in MM:SS.s format", async () => {
    render(<HandViewer episodeId="GX010085" />);
    await waitFor(() => expect(screen.queryByText(/loading/)).toBeNull());
    expect(screen.getByText(/00:00\.0/)).toBeTruthy();
  });
});

it("renders depth video element when depth_video_ready=true", async () => {
  render(<HandViewer episodeId="GX010085" />);
  await waitFor(() => expect(screen.queryByText(/loading/)).toBeNull());
  const videos = document.querySelectorAll("video");
  expect(videos.length).toBe(2);
  const srcs = Array.from(videos).map((v) => v.getAttribute("src"));
  expect(srcs.some((s) => s?.endsWith("/depth_video"))).toBe(true);
});
