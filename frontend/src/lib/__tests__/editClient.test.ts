/** Phase 5 B r1 T13: PATCH client + run-name parser. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  patchSegmentPhase,
  runNameFromManifestUrl,
} from "../editClient";

const OK_HASH = "sha256:" + "a".repeat(64);
const NEW_HASH = "sha256:" + "b".repeat(64);

function manifestStub(runHash: string) {
  return {
    schema_version: "1.0.0",
    episode_id: "ep0",
    run_hash: runHash,
    // not exhaustive — tests don't validate the full Manifest shape.
  };
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("runNameFromManifestUrl", () => {
  it("extracts name from /api/runs/<name>/manifest.json", () => {
    expect(
      runNameFromManifestUrl(
        "http://localhost:5173/api/runs/ep0__abc123/manifest.json",
      ),
    ).toBe("ep0__abc123");
  });

  it("extracts name from /runs/<name>/manifest.json (static mode)", () => {
    expect(
      runNameFromManifestUrl(
        "http://localhost:5173/runs/ep0__abc123/manifest.json",
      ),
    ).toBe("ep0__abc123");
  });

  it("ignores query string", () => {
    expect(
      runNameFromManifestUrl(
        "http://localhost:5173/api/runs/ep0__abc/manifest.json?cb=42",
      ),
    ).toBe("ep0__abc");
  });

  it("throws if path does not end with /manifest.json", () => {
    expect(() =>
      runNameFromManifestUrl("http://localhost:5173/api/runs/ep0__abc/"),
    ).toThrow();
  });
});

describe("patchSegmentPhase — happy path", () => {
  it("sends correct PATCH and parses 200 + ETag", async () => {
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify(manifestStub(NEW_HASH)), {
        status: 200,
        headers: {
          "ETag": `"${NEW_HASH}"`,
          "Content-Type": "application/json",
        },
      }),
    );

    const result = await patchSegmentPhase({
      apiBase: "/api/runs/",
      runName: "ep0__abc",
      segmentId: "seg-001",
      newPhase: "grasp_object",
      ifMatchRunHash: OK_HASH,
    });

    expect(result.kind).toBe("ok");
    if (result.kind !== "ok") return;
    expect(result.runHash).toBe(NEW_HASH);
    expect(result.manifest.run_hash).toBe(NEW_HASH);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const call = fetchMock.mock.calls[0];
    const url = call[0] as string;
    const init = call[1] as RequestInit;
    expect(url).toBe("/api/runs/ep0__abc/segments/seg-001");
    expect(init.method).toBe("PATCH");
    const headers = new Headers(init.headers);
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(headers.get("If-Match")).toBe(`"${OK_HASH}"`);
    const bodyStr =
      typeof init.body === "string"
        ? init.body
        : new TextDecoder().decode(init.body as ArrayBuffer);
    const bodyParsed = JSON.parse(bodyStr);
    expect(bodyParsed).toEqual({ phase: "grasp_object" });
    // Server rejects extra keys; helper must never add reviewer/etc.
    expect(Object.keys(bodyParsed)).toHaveLength(1);
  });
});

function errorResponse(
  status: number,
  body: { error: string; message: string },
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

async function callPatch() {
  return patchSegmentPhase({
    apiBase: "/api/runs/",
    runName: "ep0__abc",
    segmentId: "seg-001",
    newPhase: "grasp_object",
    ifMatchRunHash: OK_HASH,
  });
}

describe("patchSegmentPhase — runSet query param (S-RS)", () => {
  it("appends ?run_set= when runSet is provided", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      new Response(JSON.stringify(manifestStub(NEW_HASH)), {
        status: 200,
        headers: { "ETag": `"${NEW_HASH}"`, "Content-Type": "application/json" },
      }),
    );
    await patchSegmentPhase({
      apiBase: "/api/runs/",
      runName: "ep0__abc",
      segmentId: "seg-001",
      newPhase: "grasp_object",
      ifMatchRunHash: OK_HASH,
      runSet: "so101_phase4_v5",
    });
    const url = vi.mocked(globalThis.fetch).mock.calls[0][0] as string;
    expect(url).toBe("/api/runs/ep0__abc/segments/seg-001?run_set=so101_phase4_v5");
  });

  it("does not append ?run_set= when runSet is '.'", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      new Response(JSON.stringify(manifestStub(NEW_HASH)), {
        status: 200,
        headers: { "ETag": `"${NEW_HASH}"`, "Content-Type": "application/json" },
      }),
    );
    await patchSegmentPhase({
      apiBase: "/api/runs/",
      runName: "ep0__abc",
      segmentId: "seg-001",
      newPhase: "grasp_object",
      ifMatchRunHash: OK_HASH,
      runSet: ".",
    });
    const url = vi.mocked(globalThis.fetch).mock.calls[0][0] as string;
    expect(url).toBe("/api/runs/ep0__abc/segments/seg-001");
  });

  it("does not append ?run_set= when runSet is undefined", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      new Response(JSON.stringify(manifestStub(NEW_HASH)), {
        status: 200,
        headers: { "ETag": `"${NEW_HASH}"`, "Content-Type": "application/json" },
      }),
    );
    await patchSegmentPhase({
      apiBase: "/api/runs/",
      runName: "ep0__abc",
      segmentId: "seg-001",
      newPhase: "grasp_object",
      ifMatchRunHash: OK_HASH,
    });
    const url = vi.mocked(globalThis.fetch).mock.calls[0][0] as string;
    expect(url).toBe("/api/runs/ep0__abc/segments/seg-001");
  });
});

describe("patchSegmentPhase — 412 etag_mismatch", () => {
  it("maps to kind=conflict with error code preserved", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      errorResponse(412, {
        error: "etag_mismatch",
        message: "If-Match did not equal current run_hash",
      }),
    );
    const r = await callPatch();
    expect(r.kind).toBe("conflict");
    if (r.kind === "conflict") {
      expect(r.errorCode).toBe("etag_mismatch");
      expect(r.serverMessage).toMatch(/If-Match/);
    }
  });

  it("ignores any stray ETag header on 412 (review NEW CONCERN #3)", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      new Response(
        JSON.stringify({ error: "etag_mismatch", message: "x" }),
        {
          status: 412,
          headers: {
            "Content-Type": "application/json",
            "ETag": `"${NEW_HASH}"`,
          },
        },
      ),
    );
    const r = await callPatch();
    expect(r.kind).toBe("conflict");
    // Even with a stray ETag, no runHash leaks out of the conflict branch.
    if (r.kind === "conflict") {
      // @ts-expect-error runHash is not in the conflict variant
      expect(r.runHash).toBeUndefined();
    }
  });
});

describe("patchSegmentPhase — 400 invalid sub-codes", () => {
  for (const code of ["invalid_label", "invalid_segment", "invalid_body"]) {
    it(`maps 400 ${code} to kind=invalid`, async () => {
      vi.mocked(globalThis.fetch).mockResolvedValueOnce(
        errorResponse(400, { error: code, message: `bad ${code}` }),
      );
      const r = await callPatch();
      expect(r.kind).toBe("invalid");
      if (r.kind === "invalid") {
        expect(r.errorCode).toBe(code);
        expect(r.serverMessage).toBe(`bad ${code}`);
      }
    });
  }
});

describe("patchSegmentPhase — 404 + 500", () => {
  it("maps 404 run_not_found to kind=not_found", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      errorResponse(404, {
        error: "run_not_found",
        message: "no such run",
      }),
    );
    const r = await callPatch();
    expect(r.kind).toBe("not_found");
    if (r.kind === "not_found") {
      expect(r.errorCode).toBe("run_not_found");
    }
  });

  it("maps 500 to kind=error with passthrough message", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      new Response("internal explosion", { status: 500 }),
    );
    const r = await callPatch();
    expect(r.kind).toBe("error");
    if (r.kind === "error") {
      expect(r.httpStatus).toBe(500);
      expect(r.errorCode).toBeNull();
    }
  });
});
