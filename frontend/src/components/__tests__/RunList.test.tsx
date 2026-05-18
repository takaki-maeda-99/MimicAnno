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

const RUN_SETS_MULTI = [
  { name: "so101_phase4_v5", label: "so101_phase4_v5" },
  { name: "piper_phase4_v5", label: "piper_phase4_v5" },
];

const RUN_SETS_LEGACY = [{ name: ".", label: "(root)" }];

beforeEach(() => {
  vi.spyOn(window, "fetch").mockImplementation(
    vi.fn(async (url: string) => {
      if (url.includes("/api/hands/index.json")) return jsonResp(HAND_INDEX);
      if (url === "/api/run-sets") return jsonResp(RUN_SETS_LEGACY);
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
  await waitFor(() => screen.getByText("Hand data"));
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
  expect(screen.queryByText("Hand data")).toBeNull();
});

it("signals_ready=false shows signals-not-generated label", async () => {
  renderWithProvider();
  await waitFor(() => screen.getByText("Hand data"));
  expect(screen.getByText("(signals not generated)")).toBeTruthy();
  const links = screen.getAllByRole("link");
  const handLinks = links.filter((l) => l.getAttribute("href")?.includes("hand=GX010086"));
  expect(handLinks).toHaveLength(0);
});

// ----- S-RS: run-set dropdown -----

it("shows run-set dropdown when multiple run-sets are available", async () => {
  vi.spyOn(window, "fetch").mockImplementation(
    vi.fn(async (url: string) => {
      if (url.includes("/api/hands/index.json")) return jsonResp(HAND_INDEX);
      if (url === "/api/run-sets") return jsonResp(RUN_SETS_MULTI);
      return jsonResp(INDEX_DOC);
    }) as typeof fetch,
  );
  renderWithProvider();
  await waitFor(() => screen.getByRole("combobox", { name: /run.set/i }));
  const select = screen.getByRole("combobox", { name: /run.set/i });
  const options = select.querySelectorAll("option");
  expect(options).toHaveLength(3);
  expect(options[0].value).toBe(".");
  expect(options[0].textContent).toBe("all (merged)");
  expect(options[1].value).toBe("so101_phase4_v5");
  expect(options[2].value).toBe("piper_phase4_v5");
});

it("does not show run-set dropdown in legacy mode (single entry)", async () => {
  // beforeEach mock returns RUN_SETS_LEGACY (1 entry with name=".")
  renderWithProvider();
  await waitFor(() => screen.getByText("ep0"));
  expect(screen.queryByRole("combobox", { name: /run.set/i })).toBeNull();
});

it("does not show run-set dropdown when apiEnabled=false", async () => {
  render(
    <ApiToggleProvider apiEnabled={false}>
      <RunList />
    </ApiToggleProvider>,
  );
  // In static mode: no /api/run-sets call, no dropdown.
  await waitFor(() => screen.getByText("ep0"));
  expect(screen.queryByRole("combobox", { name: /run.set/i })).toBeNull();
});

it("renders rows from a merged index with per-row run_set in nav links and a run_set column", async () => {
  const MERGED_INDEX = {
    schema_version: "0.1.0",
    runs: [
      {
        episode_id: "ep0",
        run_hash: "sha256:" + "a".repeat(64),
        run_hash_short: "aaaaaaaa",
        config_hash_short: "cfg00000",
        input_hash_short: "inp00000",
        manifest_url: "ep0__aaaaaaaa/manifest.json",
        task_text: "task-A",
        pipeline_phase: 4,
        generated_at: "2026-01-01T00:00:00Z",
        run_set: "so101_phase4_v5",
      },
      {
        episode_id: "ep1",
        run_hash: "sha256:" + "b".repeat(64),
        run_hash_short: "bbbbbbbb",
        config_hash_short: "cfg00001",
        input_hash_short: "inp00001",
        manifest_url: "ep1__bbbbbbbb/manifest.json",
        task_text: "task-B",
        pipeline_phase: 4,
        generated_at: "2026-01-02T00:00:00Z",
        run_set: "piper_phase4_v5",
      },
    ],
  };
  vi.spyOn(window, "fetch").mockImplementation(
    vi.fn(async (url: string) => {
      if (url.includes("/api/hands/index.json")) return jsonResp(HAND_INDEX);
      if (url === "/api/run-sets") return jsonResp(RUN_SETS_MULTI);
      return jsonResp(MERGED_INDEX);
    }) as typeof fetch,
  );

  renderWithProvider();

  const link0 = await screen.findByRole("link", { name: "ep0" });
  expect(link0.getAttribute("href")).toContain("run_set=so101_phase4_v5");
  const link1 = await screen.findByRole("link", { name: "ep1" });
  expect(link1.getAttribute("href")).toContain("run_set=piper_phase4_v5");
  // Column header present
  expect(screen.getByRole("columnheader", { name: "run_set" })).toBeTruthy();
  // Per-row run_set text shown (getAllByText because the value also appears in the dropdown)
  expect(screen.getAllByText("so101_phase4_v5").length).toBeGreaterThan(0);
  expect(screen.getAllByText("piper_phase4_v5").length).toBeGreaterThan(0);
});
