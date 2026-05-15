/** Phase 5 B r1 T12: ApiToggleContext + apiBase wiring. */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ApiToggleProvider, useApiToggle } from "../ApiToggleContext";
import { resolveUrl } from "../manifest";

function Probe() {
  const { apiEnabled, apiBase } = useApiToggle();
  return (
    <>
      <span data-testid="enabled">{apiEnabled ? "yes" : "no"}</span>
      <span data-testid="base">{apiBase}</span>
    </>
  );
}

describe("ApiToggleProvider", () => {
  it("apiEnabled=true → apiBase is /api/runs/", () => {
    render(
      <ApiToggleProvider apiEnabled={true}>
        <Probe />
      </ApiToggleProvider>,
    );
    expect(screen.getByTestId("enabled").textContent).toBe("yes");
    expect(screen.getByTestId("base").textContent).toBe("/api/runs/");
  });

  it("apiEnabled=false → apiBase is /runs/", () => {
    render(
      <ApiToggleProvider apiEnabled={false}>
        <Probe />
      </ApiToggleProvider>,
    );
    expect(screen.getByTestId("enabled").textContent).toBe("no");
    expect(screen.getByTestId("base").textContent).toBe("/runs/");
  });

  it("useApiToggle outside Provider returns default (apiEnabled=false)", () => {
    render(<Probe />);
    expect(screen.getByTestId("enabled").textContent).toBe("no");
    expect(screen.getByTestId("base").textContent).toBe("/runs/");
  });
});

describe("resolveUrl with apiBase", () => {
  it("resolves artifacts under /api/runs/ when API mode is on", () => {
    const manifestUrl =
      "http://localhost:5173/api/runs/ep0__abc/manifest.json";
    expect(resolveUrl(manifestUrl, "video.mp4")).toBe(
      "http://localhost:5173/api/runs/ep0__abc/video.mp4",
    );
  });

  it("resolves artifacts under /runs/ when API mode is off", () => {
    const manifestUrl =
      "http://localhost:5173/runs/ep0__abc/manifest.json";
    expect(resolveUrl(manifestUrl, "video.mp4")).toBe(
      "http://localhost:5173/runs/ep0__abc/video.mp4",
    );
  });
});
