/** U-A3 — VlmPanel + vlmClient tests (master §2.4 rev3). */
import { describe, it, expect, vi, afterEach } from "vitest";
import {
  render, screen, fireEvent, waitFor, act,
} from "@testing-library/react";
import VlmPanel from "../VlmPanel";
import type { VlmCall, VlmDumps } from "../../lib/vlmClient";
import { fetchVlmDumps } from "../../lib/vlmClient";

// ---------------------------------------------------------------------------
// Fixture helpers — rev3 schema
// ---------------------------------------------------------------------------

function plannerCall(overrides: Partial<VlmCall> = {}): VlmCall {
  return {
    kind: "planner",
    call_id: "call_000",
    attempt: null,
    prompt: "p-prompt",
    raw_output: "{}",
    parsed: {},
    failed: false,
    frame_url: "/runs/rs1/_vlm_dumps/ep/_planner/call_000/frame.png",
    segment_ordinal: null,
    request_json: null,
    keyframe_urls: [],
    ...overrides,
  };
}

function labelerCall(overrides: Partial<VlmCall> = {}): VlmCall {
  return {
    kind: "labeler",
    call_id: "s_001__attempt_1",
    attempt: 1,
    prompt: "s-prompt",
    raw_output: "{}",
    parsed: { phase: "approach_object" },
    failed: false,
    frame_url: null,
    segment_ordinal: 1,
    request_json: null,
    keyframe_urls: [],
    ...overrides,
  };
}

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
    vi.fn(async () => new Response("{}", { status })) as typeof fetch,
  );
}

// ---------------------------------------------------------------------------
// fetchVlmDumps
// ---------------------------------------------------------------------------

describe("fetchVlmDumps", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("returns parsed body on 200", async () => {
    mockFetchOk(dump({ calls: [plannerCall()] }));
    const result = await fetchVlmDumps({
      apiBase: "", canonical: "c", runSet: "rs",
    });
    expect(result.calls).toHaveLength(1);
    // Rev3: call_id has no "_planner/" prefix
    expect(result.calls[0].call_id).toBe("call_000");
    expect(result.calls[0].kind).toBe("planner");
  });

  it("throws on non-200", async () => {
    mockFetchStatus(500);
    await expect(fetchVlmDumps({
      apiBase: "", canonical: "c", runSet: "rs",
    })).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// VlmPanel rendering
// ---------------------------------------------------------------------------

describe("VlmPanel", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("renders idle state when canonical or runSet is null", () => {
    render(
      <VlmPanel
        apiBase=""
        canonical={null}
        runSet={null}
        selectedSegmentId={null}
      />,
    );
    expect(screen.getByTestId("vlm-panel")).toBeTruthy();
  });

  it("shows 'no dumps' when API returns empty calls", async () => {
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
      expect(screen.getByText("No VLM dumps for this episode")).toBeTruthy();
    });
  });

  it("renders planner section and segments section", async () => {
    mockFetchOk(dump({
      calls: [
        plannerCall({ call_id: "call_000" }),
        labelerCall({ call_id: "s_001__attempt_1", segment_ordinal: 1 }),
        labelerCall({ call_id: "s_002__attempt_1", segment_ordinal: 2 }),
      ],
    }));
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
    expect(screen.getByTestId("vlm-call-call_000")).toBeTruthy();
    expect(screen.getByTestId("vlm-call-s_001__attempt_1")).toBeTruthy();
    expect(screen.getByTestId("vlm-call-s_002__attempt_1")).toBeTruthy();
  });

  it("highlights labeler row by segment_ordinal matching selectedSegmentId", async () => {
    mockFetchOk(dump({
      calls: [
        labelerCall({
          call_id: "s_001__attempt_1",
          segment_ordinal: 1,
        }),
        labelerCall({
          call_id: "s_002__attempt_1",
          segment_ordinal: 2,
        }),
      ],
    }));
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
        screen.getByTestId("vlm-call-s_002__attempt_1").getAttribute("data-selected"),
      ).toBe("true");
      expect(
        screen.getByTestId("vlm-call-s_001__attempt_1").getAttribute("data-selected"),
      ).toBe("false");
    });
  });

  it("marks failed rows with data-failed=true", async () => {
    mockFetchOk(dump({
      calls: [
        labelerCall({
          call_id: "s_001__attempt_1",
          failed: true,
          parsed: null,
          raw_output: "bad",
        }),
      ],
    }));
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
        screen.getByTestId("vlm-call-s_001__attempt_1").getAttribute("data-failed"),
      ).toBe("true");
    });
  });

  it("clicking a row expands prompt + raw + parsed", async () => {
    mockFetchOk(dump({
      calls: [
        labelerCall({
          call_id: "s_001__attempt_1",
          prompt: "the full prompt",
          raw_output: '{"x":1}',
          parsed: { x: 1 },
        }),
      ],
    }));
    render(
      <VlmPanel
        apiBase=""
        canonical="c"
        runSet="rs"
        selectedSegmentId={null}
      />,
    );
    await waitFor(() => {
      expect(screen.getByTestId("vlm-call-s_001__attempt_1")).toBeTruthy();
    });
    const btn = screen.getByTestId("vlm-call-s_001__attempt_1")
      .querySelector("button")!;
    act(() => fireEvent.click(btn));
    expect(screen.getByTestId("vlm-expanded-s_001__attempt_1")).toBeTruthy();
    expect(screen.getByTestId("vlm-prompt-full").textContent).toBe(
      "the full prompt",
    );
    expect(screen.getByTestId("vlm-raw-output").textContent).toContain("x");
  });

  it("shows keyframe images when expanded for labeler call", async () => {
    mockFetchOk(dump({
      calls: [
        labelerCall({
          call_id: "s_001__attempt_1",
          keyframe_urls: [
            "/runs/rs1/_vlm_dumps/ep/s_001/attempt_1/keyframe_000.png",
            "/runs/rs1/_vlm_dumps/ep/s_001/attempt_1/keyframe_001.png",
          ],
        }),
      ],
    }));
    render(
      <VlmPanel
        apiBase=""
        canonical="c"
        runSet="rs"
        selectedSegmentId={null}
      />,
    );
    await waitFor(() => {
      expect(screen.getByTestId("vlm-call-s_001__attempt_1")).toBeTruthy();
    });
    const btn = screen.getByTestId("vlm-call-s_001__attempt_1")
      .querySelector("button")!;
    act(() => fireEvent.click(btn));
    const kfDiv = screen.getByTestId("vlm-keyframes");
    expect(kfDiv.querySelectorAll("img")).toHaveLength(2);
  });

  it("shows request_json when expanded", async () => {
    const reqJson = { frames: [0, 1, 2], context: "test" };
    mockFetchOk(dump({
      calls: [
        labelerCall({
          call_id: "s_001__attempt_1",
          request_json: reqJson,
        }),
      ],
    }));
    render(
      <VlmPanel
        apiBase=""
        canonical="c"
        runSet="rs"
        selectedSegmentId={null}
      />,
    );
    await waitFor(() => {
      expect(screen.getByTestId("vlm-call-s_001__attempt_1")).toBeTruthy();
    });
    const btn = screen.getByTestId("vlm-call-s_001__attempt_1")
      .querySelector("button")!;
    act(() => fireEvent.click(btn));
    const reqPre = screen.getByTestId("vlm-request-json");
    expect(reqPre.textContent).toContain("frames");
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

  it("kind badge shows 'planner' or 'labeler'", async () => {
    mockFetchOk(dump({
      calls: [
        plannerCall({ call_id: "call_000" }),
        labelerCall({ call_id: "s_001__attempt_1", segment_ordinal: 1 }),
      ],
    }));
    render(
      <VlmPanel
        apiBase=""
        canonical="c"
        runSet="rs"
        selectedSegmentId={null}
      />,
    );
    await waitFor(() => {
      expect(screen.getByTestId("vlm-planner-section")).toBeTruthy();
    });
    const badges = screen.getAllByTestId("vlm-kind-badge");
    const badgeTexts = badges.map((b) => b.textContent);
    expect(badgeTexts).toContain("planner");
    expect(badgeTexts).toContain("labeler");
    // Must NOT contain legacy "segment" kind
    expect(badgeTexts).not.toContain("segment");
  });
});
