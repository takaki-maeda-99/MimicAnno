import { it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import RunList from "../RunList";
import { ApiToggleProvider } from "../../lib/ApiToggleContext";

const INDEX_DOC = {
  schema_version: "0.1.0",
  runs: [
    {
      episode_id: "ep0",
      run_hash: "sha256:" + "a".repeat(64),
      run_hash_short: "aaaaaaaa",
      config_hash_short: "cfg00000",
      input_hash_short: "inp00000",
      manifest_url: "ep0__aaaaaaaa/manifest.json",
      task_text: "pick up tape",
      pipeline_phase: 4,
      generated_at: "2026-05-14T00:00:00Z",
    },
  ],
};

const HAND_INDEX = {
  schema_version: "0.1.0",
  episodes: [
    { episode_id: "GX010085", signals_ready: true },
    { episode_id: "GX010086", signals_ready: false },
  ],
};

function jsonResp(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  vi.spyOn(window, "fetch").mockImplementation(
    vi.fn(async (url: string) => {
      if (url.includes("/api/hands/index.json")) return jsonResp(HAND_INDEX);
      return jsonResp(INDEX_DOC);
    }) as typeof fetch,
  );
});

afterEach(() => {
  vi.restoreAllMocks();
});

function renderWithProvider() {
  return render(
    <ApiToggleProvider apiEnabled={true}>
      <RunList />
    </ApiToggleProvider>,
  );
}

it("shows hand episode links when /api/hands/index.json returns episodes", async () => {
  renderWithProvider();
  await waitFor(() => screen.getByText("手のデータ"));
  const link = screen.getByRole("link", { name: "GX010085" });
  expect(link.getAttribute("href")).toContain("hand=GX010085");
});

it("does not show hand section when /api/hands/index.json returns 503", async () => {
  vi.spyOn(window, "fetch").mockImplementation(
    vi.fn(async (url: string) => {
      if (url.includes("/api/hands/index.json")) return new Response("{}", { status: 503 });
      return jsonResp(INDEX_DOC);
    }) as typeof fetch,
  );
  renderWithProvider();
  await waitFor(() => screen.getByText("ep0"));
  expect(screen.queryByText("手のデータ")).toBeNull();
});

it("signals_ready=false shows signals未生成 label", async () => {
  renderWithProvider();
  await waitFor(() => screen.getByText("手のデータ"));
  expect(screen.getByText("(signals未生成)")).toBeTruthy();
  const links = screen.getAllByRole("link");
  const handLinks = links.filter((l) => l.getAttribute("href")?.includes("hand=GX010086"));
  expect(handLinks).toHaveLength(0);
});
