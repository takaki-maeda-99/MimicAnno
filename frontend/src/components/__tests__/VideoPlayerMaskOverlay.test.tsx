/** U-A4 FT8-FT9: VideoPlayer maskOverlay prop tests. */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import VideoPlayer from "../VideoPlayer";

describe("VideoPlayer maskOverlay prop", () => {
  // FT8: maskOverlay prop renders inside relative wrapper
  it("FT8: renders maskOverlay child inside wrapper div", () => {
    render(
      <VideoPlayer
        videoUrl="http://example.com/v.mp4"
        currentTimeSec={0}
        onTimeChange={() => undefined}
        onError={() => undefined}
        maskOverlay={<div data-testid="sentinel">overlay</div>}
      />,
    );
    expect(screen.getByTestId("sentinel")).toBeDefined();
  });

  // FT9: without maskOverlay prop, video still renders (backward compat)
  it("FT9: omitting maskOverlay renders video without error", () => {
    const { container } = render(
      <VideoPlayer
        videoUrl="http://example.com/v.mp4"
        currentTimeSec={0}
        onTimeChange={() => undefined}
        onError={() => undefined}
      />,
    );
    const video = container.querySelector("video");
    expect(video).not.toBeNull();
  });
});
