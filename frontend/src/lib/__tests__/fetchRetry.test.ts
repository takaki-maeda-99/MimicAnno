import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fetchRetry } from "../fetchRetry";

describe("fetchRetry", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

  it("returns the first successful response", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(new Response("ok", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const r = await fetchRetry("https://x/y");
    expect(r.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("retries up to 3 times on 404, then succeeds", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response("nope", { status: 404 }))
      .mockResolvedValueOnce(new Response("nope", { status: 404 }))
      .mockResolvedValueOnce(new Response("ok", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const promise = fetchRetry("https://x/y");
    await vi.runAllTimersAsync();
    const r = await promise;
    expect(r.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("throws after 3 consecutive 404s", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("nope", { status: 404 }));
    vi.stubGlobal("fetch", fetchMock);
    const promise = fetchRetry("https://x/y");
    const assertion = expect(promise).rejects.toThrow(/404/);
    await vi.runAllTimersAsync();
    await assertion;
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("does not retry on 500", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("err", { status: 500 }));
    vi.stubGlobal("fetch", fetchMock);
    const promise = fetchRetry("https://x/y");
    const assertion = expect(promise).rejects.toThrow(/500/);
    await vi.runAllTimersAsync();
    await assertion;
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("propagates network errors immediately (no retry)", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("network failure"));
    vi.stubGlobal("fetch", fetchMock);
    const promise = fetchRetry("https://x/y");
    const assertion = expect(promise).rejects.toThrow(/network failure/);
    await vi.runAllTimersAsync();
    await assertion;
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("propagates AbortError without retrying", async () => {
    const controller = new AbortController();
    const fetchMock = vi.fn().mockImplementation((_, init) => {
      const reason = (init as RequestInit | undefined)?.signal?.aborted
        ? new DOMException("aborted", "AbortError")
        : new Response("nope", { status: 404 });
      if (reason instanceof Response) return Promise.resolve(reason);
      return Promise.reject(reason);
    });
    vi.stubGlobal("fetch", fetchMock);
    controller.abort();
    const promise = fetchRetry("https://x/y", { signal: controller.signal });
    const assertion = expect(promise).rejects.toThrow(/abort/i);
    await vi.runAllTimersAsync();
    await assertion;
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
