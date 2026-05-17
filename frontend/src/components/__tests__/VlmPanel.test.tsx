/** U-A3 — VlmPanel + vlmClient tests. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render, screen, fireEvent, waitFor, act,
} from "@testing-library/react";
import VlmPanel from "../VlmPanel";
import type { VlmDumps } from "../../lib/vlmClient";
import { fetchVlmDumps } from "../../lib/vlmClient";

function dump(overrides: Partial<VlmDumps> = {}): VlmDumps {
  return {
    canonical: "episode_000000__abc",
    run_set: "rs1",
    episode_id: "episode_000000",
    calls: [],
    ...overrides,
  };
}

function mockFetchOk(body: VlmDumps): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ) as typeof fetch,
  );
}

function mockFetchStatus(status: number): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      new Response("{}", { status }),
    ) as typeof fetch,
  );
}


describe("fetchVlmDumps", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("returns parsed body on 200", async () => {
    mockFetchOk(dump({ calls: [{
      call_id: "_planner/call_000",
      kind: "planner",
      phase: null,
      segment_id: null,
      prompt: "p",
      raw_output: "{}",
      parsed: {},
      failed: false,
      ms: null,
      model_variant: null,
    }] }));
    const result = await fetchVlmDumps({
      apiBase: "", canonical: "c", runSet: "rs",
    });
    expect(result.calls).toHaveLength(1);
    expect(result.calls[0].call_id).toBe("_planner/call_000");
  });

  it("throws on non-200", async () => {
    mockFetchStatus(500);
    await expect(fetchVlmDumps({
      apiBase: "", canonical: "c", runSet: "rs",
    })).rejects.toThrow();
  });
});


describe("VlmPanel", () => {
  beforeEach(() => {
    // Each test stubs fetch explicitly.
  });
  afterEach(() => vi.unstubAllGlobals());

  it("renders empty state when canonical or runSet is null", () => {
    render(
      <VlmPanel
        apiBase=""
        canonical={null}
        runSet={null}
        selectedSegmentId={null}
      />,
    );
    // idle state renders an empty aside
    expect(screen.getByTestId("vlm-panel")).toBeTruthy();
  });

  it("shows loading then 'no dumps' when API returns empty calls", async () => {
    mockFetchOk(dump({ calls: [] }));
    render(
      <VlmPanel
        apiBase=""
        canonical="episode_000000__abc"
        runSet="rs1"
        selectedSegmentId={null}
      />,
    );
    await waitFor(() => {
      expect(
        screen.getByText("No VLM dumps for this episode"),
      ).toBeTruthy();
    });
  });

  it("renders planner section then segment section, sorted", async () => {
    mockFetchOk(dump({ calls: [
      {
        call_id: "_planner/call_000", kind: "planner", phase: null,
        segment_id: null, prompt: "p-prompt", raw_output: "{}",
        parsed: {}, failed: false, ms: null, model_variant: null,
      },
      {
        call_id: "s_001/attempt_1", kind: "segment", phase: "approach_object",
        segment_id: "s_001", prompt: "s-prompt", raw_output: "{}",
        parsed: { phase: "approach_object" },
        failed: false, ms: null, model_variant: null,
      },
      {
        call_id: "s_002/attempt_1", kind: "segment", phase: "grasp_object",
        segment_id: "s_002", prompt: "s-prompt", raw_output: "{}",
        parsed: { phase: "grasp_object" },
        failed: false, ms: null, model_variant: null,
      },
    ] }));
    render(
      <VlmPanel
        apiBase=""
        canonical="episode_000000__abc"
        runSet="rs1"
        selectedSegmentId={null}
      />,
    );
    await waitFor(() => {
      expect(screen.getByTestId("vlm-planner-section")).toBeTruthy();
      expect(screen.getByTestId("vlm-segments-section")).toBeTruthy();
    });
    expect(screen.getByTestId("vlm-call-_planner/call_000")).toBeTruthy();
    expect(screen.getByTestId("vlm-call-s_001/attempt_1")).toBeTruthy();
    expect(screen.getByTestId("vlm-call-s_002/attempt_1")).toBeTruthy();
  });

  it("highlights segment row whose segment_id matches selectedSegmentId", async () => {
    mockFetchOk(dump({ calls: [
      {
        call_id: "s_001/attempt_1", kind: "segment", phase: "approach_object",
        segment_id: "s_001", prompt: "p", raw_output: "{}",
        parsed: null, failed: false, ms: null, model_variant: null,
      },
      {
        call_id: "s_002/attempt_1", kind: "segment", phase: "grasp_object",
        segment_id: "s_002", prompt: "p", raw_output: "{}",
        parsed: null, failed: false, ms: null, model_variant: null,
      },
    ] }));
    render(
      <VlmPanel
        apiBase=""
        canonical="episode_000000__abc"
        runSet="rs1"
        selectedSegmentId="s_002"
      />,
    );
    await waitFor(() => {
      expect(
        screen.getByTestId("vlm-call-s_002/attempt_1").getAttribute("data-selected"),
      ).toBe("true");
      expect(
        screen.getByTestId("vlm-call-s_001/attempt_1").getAttribute("data-selected"),
      ).toBe("false");
    });
  });

  it("marks failed rows with data-failed=true", async () => {
    mockFetchOk(dump({ calls: [
      {
        call_id: "s_001/attempt_1", kind: "segment", phase: null,
        segment_id: "s_001", prompt: "p", raw_output: "bad",
        parsed: null, failed: true, ms: null, model_variant: null,
      },
    ] }));
    render(
      <VlmPanel
        apiBase=""
        canonical="c"
        runSet="rs"
        selectedSegmentId={null}
      />,
    );
    await waitFor(() => {
      expect(
        screen.getByTestId("vlm-call-s_001/attempt_1").getAttribute("data-failed"),
      ).toBe("true");
    });
  });

  it("clicking a row expands prompt + raw + parsed", async () => {
    mockFetchOk(dump({ calls: [
      {
        call_id: "s_001/attempt_1", kind: "segment", phase: "approach_object",
        segment_id: "s_001", prompt: "the full prompt",
        raw_output: '{"x":1}', parsed: { x: 1 }, failed: false,
        ms: null, model_variant: null,
      },
    ] }));
    render(
      <VlmPanel
        apiBase=""
        canonical="c"
        runSet="rs"
        selectedSegmentId={null}
      />,
    );
    await waitFor(() => {
      expect(screen.getByTestId("vlm-call-s_001/attempt_1")).toBeTruthy();
    });
    const btn = screen.getByTestId("vlm-call-s_001/attempt_1")
      .querySelector("button")!;
    act(() => fireEvent.click(btn));
    expect(screen.getByTestId("vlm-expanded-s_001/attempt_1")).toBeTruthy();
    expect(screen.getByTestId("vlm-prompt-full").textContent)
      .toBe("the full prompt");
  });

  it("renders error state when fetch throws", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("oops", { status: 500 })) as typeof fetch,
    );
    render(
      <VlmPanel
        apiBase=""
        canonical="c"
        runSet="rs"
        selectedSegmentId={null}
      />,
    );
    await waitFor(() => {
      expect(screen.getByRole("alert").textContent).toMatch(/VLM dumps error/);
    });
  });
});
