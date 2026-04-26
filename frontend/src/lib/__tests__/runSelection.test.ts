import { describe, it, expect } from "vitest";
import { selectRun } from "../runSelection";
import type { IndexEntry } from "../manifest";

const ent = (overrides: Partial<IndexEntry> = {}): IndexEntry => ({
  episode_id: "ep_000",
  run_hash: "sha256:aaaaaaaaaaaaaaaaaaaa",
  run_hash_short: "aaaaaaaaaaaa",
  config_hash_short: "cccccccc",
  input_hash_short: "iiiiiiii",
  manifest_url: "ep_000__aaaaaaaaaaaa/manifest.json",
  task_text: "t",
  pipeline_phase: 1,
  generated_at: "2026-04-26T00:00:00Z",
  ...overrides,
});

describe("selectRun", () => {
  it("returns kind=none when episode_id not present", () => {
    const r = selectRun([ent({ episode_id: "ep_other" })], "ep_000", undefined);
    expect(r).toEqual({ kind: "none", episodeId: "ep_000", runHashShort: undefined });
  });
  it("returns kind=single when exactly one matches", () => {
    const e = ent();
    const r = selectRun([e], "ep_000", undefined);
    expect(r).toEqual({ kind: "single", entry: e });
  });
  it("returns kind=multiple, newest first, when more than one and no hash given", () => {
    const older = ent({ run_hash_short: "aaaaaaaaaaaa", generated_at: "2026-04-26T00:00:00Z" });
    const newer = ent({ run_hash_short: "bbbbbbbbbbbb", generated_at: "2026-04-26T01:00:00Z" });
    const r = selectRun([older, newer], "ep_000", undefined);
    expect(r.kind).toBe("multiple");
    if (r.kind === "multiple") {
      expect(r.chosen).toEqual(newer);
      expect(r.alternatives).toEqual([older]);
    }
  });
  it("returns kind=single when the hash filter narrows to one", () => {
    const a = ent({ run_hash_short: "aaaaaaaaaaaa" });
    const b = ent({ run_hash_short: "bbbbbbbbbbbb" });
    const r = selectRun([a, b], "ep_000", "bbbbbbbbbbbb");
    expect(r).toEqual({ kind: "single", entry: b });
  });
  it("returns kind=none when the hash does not match any entry", () => {
    const a = ent({ run_hash_short: "aaaaaaaaaaaa" });
    const b = ent({ run_hash_short: "bbbbbbbbbbbb" });
    const r = selectRun([a, b], "ep_000", "deadbeefdead");
    expect(r).toEqual({ kind: "none", episodeId: "ep_000", runHashShort: "deadbeefdead" });
  });
  it("breaks ties on equal generated_at by run_hash lex order", () => {
    const a = ent({ run_hash: "sha256:aaaa", run_hash_short: "aaaaaaaaaaaa" });
    const b = ent({ run_hash: "sha256:bbbb", run_hash_short: "bbbbbbbbbbbb" });
    const r = selectRun([a, b], "ep_000", undefined);
    expect(r.kind).toBe("multiple");
    if (r.kind === "multiple") {
      expect(r.chosen.run_hash).toBe("sha256:bbbb");
    }
  });
});
