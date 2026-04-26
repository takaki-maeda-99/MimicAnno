# MimicAnno Plan 2 — Phase 1 React/Vite viewer design

Status: **draft**, awaiting review (Codex).
Author: brainstorming session 2026-04-26.
Supersedes: nothing — this is a new sub-plan.
Parent spec: [`2026-04-25-mimicanno-design-brushup.md`](./2026-04-25-mimicanno-design-brushup.md) (§3 deliverables, §4.2 Vite config, §4.4 index/routing, §5.4–§5.5 boundaries/signals schemas, §6.1–§6.6 schema/atomicity/versioning, §12 package structure, §15.1 Phase 1 exit criteria).

## 0. Scope and intent

This spec covers **Plan 2**: the read-only Phase 1 React/Vite viewer that consumes the run-directory artifacts produced by the Python pipeline (Plan 1, merged to `main` at `efec34b`). It is the **PoC-grade** viewer: enough to satisfy parent-spec §15.1 exit criteria #5, #8, #9 and to let a developer eyeball whether boundary candidates are landing where they should on a real episode. It is **not** the Phase 5 edit UI; the viewer will be largely rewritten when edit affordances arrive.

Non-goals (deferred to Phase 5 unless noted):
- Edit affordances (segment splitting/merging/relabeling, label dropdowns).
- Persistence / backend / authentication.
- Production build pipeline / CI / Lighthouse-style performance budgets (the dev server is the only supported entry point in Phase 1).
- Visual polish beyond "a developer can read it on a 1080p screen".
- e2e tests (Playwright). Unit tests cover pure helpers only; the rendering exit criterion is verified by manual browser smoke against real data.
- Accessibility (ARIA, keyboard navigation beyond what `<video>` and `<a>` give for free).
- i18n.
- Internet Explorer / Safari < latest. Phase 1 runs on Chrome / Firefox / Safari current on a developer laptop.

## 1. Architecture

### 1.1 Tooling

| Item | Choice | Why |
|---|---|---|
| Build | Vite (parent-spec §4.2 already pins this) | static dev server, ts-aware, the `serve-runs` middleware contract is already specified |
| Language | TypeScript, `strict: true` | catches manifest-shape mistakes at compile time without a Zod runtime layer |
| UI lib | React 18 | parent-spec §3 / §12 |
| Package manager | pnpm | parent-spec §4.5 (`cd frontend && pnpm dev`) |
| Styling | plain CSS in one `App.css` | YAGNI; Tailwind / CSS-in-JS adds tooling weight not needed for PoC |
| State | local React (`useState` + URL params via `URLSearchParams`) | viewer state is shallow; no global store needed until Phase 5 |
| Router | none | URL is parsed in `App.tsx` directly; one or two screens does not warrant `react-router` yet |
| Validation | hand-written TS interfaces; runtime validation deferred | Plan 1's Python writers validate against the JSON schemas at write time, so the producer side is already typed; the viewer trusts what it reads |
| Test runner | Vitest | ships with Vite; jsdom not needed because we only test pure helpers |
| Lint/format | ESLint + Prettier (Vite template defaults) | minimum noise |
| Video | native `<video>` | no library required; `timeupdate` and `currentTime=` cover the seek/playhead contract |
| Waveforms / markers | inline SVG | per-channel `<polyline>` against a shared X scale; ≤ 60 samples/sec means SVG is fast enough |

### 1.2 Directory layout

```
frontend/
  package.json
  pnpm-lock.yaml
  tsconfig.json                # strict: true; jsx: react-jsx; lib: dom + es2022
  vite.config.ts               # parent-spec §4.2 verbatim
  index.html
  src/
    main.tsx                   # ReactDOM.createRoot(<App/>)
    App.tsx                    # URL → <RunList> | <RunViewer>
    App.css                    # all visual styling lives here
    lib/
      manifest.ts              # types + URL/artifact resolvers + assertIndexSchema + assertConsumerCapability + assertArtifactSelfConsistent
      runSelection.ts          # pure routing rule (parent-spec §4.4 / §15.1 #9)
      time.ts                  # time ↔ frame helpers
      fetchRetry.ts            # 3× backoff fetch (parent-spec §6.5 publish-gap window)
      __tests__/
        manifest.test.ts
        runSelection.test.ts
        time.test.ts
        fetchRetry.test.ts
        fixtures/
          manifest.json        # committed real-data fixture for the parse test
    components/
      RunList.tsx
      RunViewer.tsx
      VideoPlayer.tsx
      Timeline.tsx
      WaveformView.tsx
      BoundaryMarkerLayer.tsx
```

### 1.3 Repository integration

- New top-level `frontend/` directory; `runs/` already exists from Plan 1.
- `.gitignore` gains `frontend/node_modules/` and `frontend/dist/`.
- No CI step in Plan 2; `pnpm test` is run by the developer.
- `pnpm install` and `pnpm dev` are the only entry points described in `frontend/README.md` (a short file, not a doc tree).

## 2. Data flow

```
URL ?run=<episodeId>[&hash=<runHashShort>]
      │
      ▼
App.tsx parses URL → either renders <RunList /> or <RunViewer episodeId hash? />
      │
      ▼
RunList: fetch("/runs/index.json")        → IndexDoc
          assertIndexSchema(doc):
            • doc.schema_version major in supportedMajors.index → continue
            • else                                              → render compat error
          render doc.runs[] (sorted by generated_at desc; empty list = "no runs yet" panel)
RunViewer:
  step 1: fetch("/runs/index.json")
          assertIndexSchema(doc) (parent-spec §6.6 — both consistency-vs-self and
                                  consumer-capability checks apply to the external
                                  index.json schema_version too)
          filter doc.runs[] by (episodeId, hash?) via lib/runSelection.selectRun():
            • 0 matches → render error message
            • 1 match → use it
            • >1 matches → use newest by generated_at;
              also render a non-modal "N runs exist" banner with chooser
              (parent-spec §4.4 routing rule)
  step 2: resolve manifest_url against /runs/index.json's base URL,
          fetchRetry it (parent-spec §6.5 publish-gap window — 3× 100 ms backoff)
                                            → Manifest
  step 3: assertConsumerCapability(manifest, supportedMajors) BEFORE artifact
          fetches — checks each role's MAJOR in `manifest.compat` against
          `supportedMajors[role]`. This is half of parent-spec §6.6 (the
          consumer-capability half, applied to the manifest's CLAIMS about
          its artifacts). Catches "viewer can't read this version" before
          three more 4xx round-trips.
  step 4: for each artifact role in {annotation, boundaries, signals}:
          resolve artifact.url against manifest's URL → fetch in parallel
                                            → AnnotationResult, BoundariesDoc, SignalsDoc
          (each fetch carries the same AbortController so a URL change while
           in flight cancels the obsolete request — see §5)
  step 5: assertArtifactSelfConsistent(role, artifact, manifest) AFTER each
          artifact resolves — checks `artifact.schema_version.major === manifest.compat[role]`.
          This is the OTHER half of parent-spec §6.6 (the producer-internal
          consistency half) and can only be done once the artifact bytes are
          in hand. A mismatch means the run directory is internally corrupt;
          surface a `<div>` error and stop.
  step 6: render
      │
      ▼
RunViewer holds:
  - currentTimeSec: number       // playhead, single source of truth
  - manifest, annotation, boundaries, signals  (immutable per render)
RunViewer wires:
  - VideoPlayer.onTimeUpdate(t)        → setCurrentTimeSec(t)
  - Timeline.onSeek(t)                 → videoRef.current.currentTime = t
                                          (browser then fires timeupdate)
```

The viewer never calls `fetch("/runs/")` to enumerate the directory; it always goes through `index.json` (parent-spec §4.4). This keeps the static-vs-backend story symmetric — Phase 5 swaps `index.json` for `GET /api/runs/index.json` of the same shape.

## 3. Components

### 3.1 Component table

| Component | Responsibility | Inputs (props) | Outputs |
|---|---|---|---|
| `App` | URL parsing → `RunList` or `RunViewer` | none | route children |
| `RunList` | fetch and list `index.json`; clicking a row navigates to `?run=&hash=` | none | `<a href>` navigation |
| `RunViewer` | fetch manifest + 3 artifacts; own `currentTimeSec`; **own `widthPx` (single `ResizeObserver`)**; **render `pipeline_status` banner when `degraded_from_phase != null`**; wire children | `episodeId, runHashShort?` | error / chooser banner / pipeline-status banner / `<RunBody>` |
| `VideoPlayer` | native `<video>`; emit `timeupdate`; accept seek | `videoUrl, currentTimeSec, onTimeChange` | `onTimeChange(t)` |
| `Timeline` | segment dividers + playhead; click → seek; **receives `widthPx` prop** | `widthPx, durationSec, currentTimeSec, candidates, segments, onSeek` | `onSeek(t)` |
| `WaveformView` | per-channel SVG `<polyline>`; Y auto-normalized per channel min/max; **receives `widthPx` prop** | `widthPx, channels, durationSec, currentTimeSec` | none |
| `BoundaryMarkerLayer` | per-source colored markers on Timeline's SVG; multi-source candidates stack; **receives `widthPx` prop** | `widthPx, candidates, durationSec` | none |

**Shared X-axis ownership.** `RunViewer` owns the X-axis width. It mounts a single `ResizeObserver` on the row container that wraps `Timeline` and `WaveformView`, stores `widthPx` in local state, and passes it as a prop to both. Children compute `scaleX(t) = (t / durationSec) * widthPx` from the prop — they MUST NOT measure the DOM themselves. First-render alignment is handled by rendering `null` (or a `<div>loading…</div>`) until the first `ResizeObserver` callback delivers a non-zero `widthPx`; this keeps `Timeline` and `WaveformView` from briefly disagreeing about pixel positions on initial mount.

`WaveformView` plots channel `i`'s value at `t = t0_sec + i * dt_sec` (parent-spec §5.5), which automatically satisfies parent-spec §15.1 exit criterion #8 (different `dt_sec` per channel still align).

**Pipeline-status banner.** When `manifest.pipeline_status.degraded_from_phase != null`, `RunViewer` renders a single-line banner above the timeline reading `"degraded from phase <N>: <degrade_reason>"` (parent-spec §4.3 — viewer is required to surface this so users do not have to scan every segment's `object_state_unavailable`). In Phase 1 this banner is dormant because Phase 1 always produces `degraded_from_phase: null`, but the contract is wired up here so Phase 3+ does not need a viewer change.

### 3.2 Source-color mapping (BoundaryMarkerLayer)

| `source` | color |
|---|---|
| `gripper_transition` | `#e63946` (red) |
| `eef_velocity_valley` | `#1d4ed8` (blue) |
| `eef_acceleration_peak` | `#16a34a` (green) |
| `action_norm_change` | `#f97316` (orange) |
| `episode_start` / `episode_end` | `#6b7280` (gray, sentinel) |

A candidate with multiple sources renders one marker per source, stacked vertically inside the Timeline's marker band, in `sorted(sources)` order. Hovering a marker shows a `<title>` tooltip with the score and source list.

### 3.3 `lib/manifest.ts` types

Hand-written interfaces matching `mimicanno/jsonschemas/*.schema.json`. Drift between the two is **not** caught by TypeScript (a `JSON.parse(...) as Manifest` cast is a no-op at runtime), so the safety net is narrow: the unit-test fixture (a real `manifest.json` committed under `src/lib/__tests__/fixtures/`) is parsed and a small set of structural assertions are made against it (key presence, `compat` block, `artifacts[]` length, `time_base === "video_pts_seconds"`). This catches the *known* shape; an unknown new field that the producer adds is silently ignored, and a producer regression that drops a known field surfaces the next time someone refreshes the fixture. Acknowledged PoC limitation; if it bites, Zod is added incrementally without restructuring components.

```ts
export type SchemaVersion = `${number}.${number}.${number}`;

export interface Manifest {
  schema_version: SchemaVersion;
  episode_id: string;
  task: { text: string; version: string | null };
  generated_at: string;
  generator: { name: string; cli_version: string; pipeline_phase: number };
  config_hash: string;
  input_hash: string;
  run_hash: string;
  model_versions: Record<string, string | null>;
  pipeline_params: { boundary: BoundaryParams };
  inputs: { video: InputRef; parquet: InputRef };
  time_base: "video_pts_seconds";
  fps: number;
  duration_sec: number;
  pipeline_status: PipelineStatus;
  compat: { manifest: number; annotation: number; boundaries: number; signals: number };
  artifacts: Artifact[];
}
// + IndexEntry, BoundaryCandidate, SignalChannel, SignalsDoc, SubtaskSegment,
//   AnnotationResult, BoundaryRef, PipelineStatus, BoundaryParams, InputRef, Artifact
```

Helpers:
- `artifactUrl(manifest: Manifest, role: "annotation" | "boundaries" | "signals" | "video"): string` — looks up the role and returns its `.url`. Throws if absent.
- `resolveUrl(baseUrl: string, relative: string): string` — wraps `new URL(relative, baseUrl).toString()`. Used by both index→manifest resolution and manifest→artifact resolution. Same single rule the parent spec mandates (§4.4 URL resolution rule).
- `assertIndexSchema(doc: { schema_version: SchemaVersion }, supportedMajors: number[])` — applied to `runs/index.json` itself; throws on consumer-capability mismatch (parent-spec §6.6 set membership for external schemas).
- `assertConsumerCapability(manifest: Manifest, supportedMajors: { manifest: number[]; annotation: number[]; boundaries: number[]; signals: number[] })` — parent-spec §6.6 consumer-capability half: each role's MAJOR in `manifest.compat` must be in `supportedMajors[role]`. Called **before** artifact fetches so an unreadable run does not generate three more 4xx round-trips before the user sees the compat error. Also checks the manifest's own `schema_version.major` against `supportedMajors.manifest`.
- `assertArtifactSelfConsistent(role: "annotation" | "boundaries" | "signals", artifact: { schema_version: SchemaVersion }, manifest: Manifest)` — parent-spec §6.6 producer-internal-consistency half: `artifact.schema_version.major` must equal `manifest.compat[role]`. Called **after** each artifact resolves; this check can only run once the artifact bytes exist. A mismatch means the run directory is internally corrupt.

The two helpers together implement both checks parent-spec §6.6 mandates. Splitting them lets the consumer-capability error happen before any artifact fetch (good UX) without skipping the producer-internal check (good correctness).

### 3.4 `lib/runSelection.ts`

Pure helper for the §4 routing rule (parent-spec §4.4). Exposed as a separate file because (a) it is the one viewer-side contract that must stay regression-stable across Phase 1 → Phase 5 even though the rest of the viewer code will be rewritten and (b) it is straightforward to unit-test without DOM (parent-spec §15.1 exit criterion #9 is just deterministic logic over `IndexEntry[]`).

```ts
export type RunSelection =
  | { kind: "none"; episodeId: string; runHashShort?: string }
  | { kind: "single"; entry: IndexEntry }
  | { kind: "multiple"; chosen: IndexEntry; alternatives: IndexEntry[] };

export function selectRun(
  entries: IndexEntry[],
  episodeId: string,
  runHashShort: string | undefined,
): RunSelection;
```

Behavior:
- 0 matches → `{ kind: "none", episodeId, runHashShort }`.
- 1 match  → `{ kind: "single", entry }`.
- >1 matches AND `runHashShort` undefined → `{ kind: "multiple", chosen: <newest by generated_at>, alternatives: <all others> }`.
- >1 matches AND `runHashShort` defined → exact-match filter; if exactly one survives, return `single`; otherwise `none`.
- Stable: ties on `generated_at` resolve by `run_hash` lex order (deterministic for tests).

### 3.5 `lib/time.ts`

Pure helpers. No DOM dependency. Tested.

```ts
export function timeToFrame(tSec: number, fps: number): number;
export function frameToTime(frame: number, fps: number): number;
export function clampTime(tSec: number, durationSec: number): number;
```

### 3.6 `lib/fetchRetry.ts`

Wraps `fetch` with retry semantics for the publish-gap window (parent-spec §6.5: between the two `os.rename` calls, `manifest.json` may transiently 404). Constants:
- `MAX_ATTEMPTS = 3`
- `BACKOFF_MS = 100`
- Retries on 404 only (not 5xx). 5xx and network errors propagate immediately because in Phase 1 there is no proxy that can produce them; they indicate a real bug.

## 4. Routing & URL contract

The viewer reads two query params off `window.location.search`:

| URL pattern | Behavior |
|---|---|
| no params | render `RunList` (newest-first) |
| `?run=<episode_id>` | filter `index.json.runs[]` by `episode_id`. **0 matches**: error page with link back to the list. **1 match**: load it. **>1 matches**: load the newest by `generated_at` AND render a non-modal banner with a `<select>` chooser of `(run_hash_short, config_hash_short, input_hash_short, generated_at, task_text)` rows (parent-spec §4.4) |
| `?run=<episode_id>&hash=<run_hash_short>` | filter by `(episode_id, run_hash_short)`; exact match → load; otherwise error page |

Selecting a row from the multi-runs chooser banner navigates to `?run=<id>&hash=<short>` — i.e., the chooser writes the URL, the URL drives the load. This keeps "what run am I looking at" unambiguous in the address bar and copy-pasteable.

Parent-spec §4.4's URL resolution rule is delegated entirely to `resolveUrl` (§3.3). The viewer never hard-codes `/runs/` — it always resolves relative URLs against the URL of the file that emitted them. This is the property that makes Phase 5's `/api/runs/...` migration a no-op for viewer code.

## 5. Error and loading states

PoC-grade — single-line `<div>` messages, no styled error pages.

| Condition | Render |
|---|---|
| any `fetch` in flight | `<div>loading…</div>` |
| `runs/index.json` 404 | `<div>runs/index.json not reachable (HTTP 404). check that the dev server is running and that mimicanno annotate has produced a run.</div>` |
| `runs/index.json` parses but `runs: []` | `<div>no runs yet. run `mimicanno annotate` to produce one.</div>` |
| `runs/index.json` other 4xx/5xx | `<div>failed to load index.json: HTTP <code></div>` |
| `runs/index.json` schema major unsupported | `<div>runs/index.json schema major <X>; viewer reads {<Y>}. update viewer.</div>` |
| `?run=<id>` 0 matches | `<div>no run for episode_id=<id></div>` |
| `?run=<id>&hash=<h>` no exact match | `<div>no run for episode_id=<id> hash=<h></div>` |
| manifest fetch 4xx/5xx after retries | `<div>failed to load manifest: HTTP <code></div>` |
| consumer-capability fails (§6.6 — `manifest.compat[role]` ∉ `supportedMajors[role]`) | `<div>this run uses schema major <X> for <role>; this viewer reads majors {<Y>}. update viewer.</div>` |
| producer-internal consistency fails (§6.6 — `artifact.schema_version.major !== manifest.compat[role]`) | `<div><role>.json claims schema major <X> but manifest.compat says <Y>. run directory is internally corrupt.</div>` |
| `annotation.json` / `boundaries.json` / `signals.json` fetch fails (4xx/5xx) | `<div>failed to load <role>: HTTP <code></div>` (one per failing role; the others still render) |
| any of those three artifacts fails JSON parse or shape assertion | `<div>malformed <role>: <reason></div>` |
| `<video>` element fires `error` | `<div>video playback failed</div>` (the rest of the timeline still renders) |
| any thrown JS error inside `RunViewer` | rendered inline error `<div>` (no error boundary stack — PoC) |

The publish-gap retry (§3.6) is invisible to the user when it succeeds; only after exhausting all 3 attempts does the manifest-error message appear.

**URL-change-during-fetch race.** If the user changes the URL (e.g., picks a different alternative from the chooser banner) while the previous run's artifacts are still in flight, the in-flight `fetch` calls MUST NOT race the new render. `RunViewer` keeps a `useRef<AbortController>` keyed off `(episodeId, runHashShort)`; on URL change it `abort()`s the previous controller and creates a new one. Aborted-fetch rejections are silently swallowed (they are not error states the user should see). This is the one piece of async discipline that is not optional even at PoC grade — without it, the screen can briefly show artifacts from the wrong run.

**CORS / mp4 codec / oversized signals.json.** Out of scope for Phase 1 — the dev-server middleware serves same-origin, the producer writes a known H.264 mp4, and `signals.json` is downsampled to ≈ 30 Hz before write (parent-spec §5.5). If real data ever violates these assumptions, the existing error rows above will fire (`<video>` error / artifact malformed) and we revisit.

## 6. Testing

### 6.1 Unit (Vitest)

- `lib/time.test.ts`: `timeToFrame` / `frameToTime` round-trip; clamp at `t=0` and `t=duration_sec`.
- `lib/manifest.test.ts`:
  - `artifactUrl(manifest, "annotation")` returns the right URL; missing role throws.
  - `resolveUrl("/runs/", "ep_000__abc/manifest.json")` resolves correctly.
  - `resolveUrl("/runs/ep_000__abc/manifest.json", "boundaries.json")` resolves to `/runs/ep_000__abc/boundaries.json`.
  - `assertIndexSchema` passes on supported major and throws on unsupported.
  - `assertConsumerCapability` passes on a valid manifest fixture; throws with role + supported-set + actual-major in the message on a mismatched-major fixture.
  - `assertArtifactSelfConsistent` passes when `artifact.schema_version.major === manifest.compat[role]`; throws with role + manifest-claimed + artifact-actual in the message on mismatch.
  - A real `manifest.json` fixture (committed under `src/lib/__tests__/fixtures/`, sourced from a `runs/` produced by the test suite) parses as `Manifest` and the structural assertions described in §3.3 pass.
- `lib/runSelection.test.ts`: covers the parent-spec §15.1 exit criterion #9 contract end-to-end as pure logic — 0 matches → `none`; 1 match → `single`; multiple matches without `hash` → newest by `generated_at` and `alternatives` populated; multiple matches with matching `hash` → `single`; multiple matches with non-matching `hash` → `none`; deterministic tie-break on equal `generated_at`.
- `lib/fetchRetry.test.ts`: with a mocked `fetch` that 404s twice then 200s, returns 200; with three 404s, throws; 500 propagates immediately (no retry).

### 6.2 Manual smoke

After implementation, the developer runs:
1. `mimicanno annotate` on the `lerobot/svla_so100_pickplace` ep0 episode (already verified by Plan 1's `--boundary-config` real-data run).
2. `cd frontend && pnpm install && pnpm dev`.
3. Open `http://localhost:5173/?run=episode_000` in Chrome. Expected: video plays; the timeline renders boundary markers (red for gripper, blue/green/orange for the other detectors) and waveforms with no console errors. Marker positions visually correspond to the gripper close in the video. Exact counts and timestamps are not asserted because they shift with detector tuning — the assertion is "boundaries land where the gripper transitions actually happen".
4. Open `?run=episode_000` after a second `mimicanno annotate --boundary-config <other.yaml>` run on the same episode. Expected: chooser banner appears; clicking the alternative entry rewrites the URL with `&hash=<short>` and reloads.
5. Open with a deliberately-bumped consumer-capability mismatch (edit `supportedMajors` to `{}` in a local diff) — expected: compat error message.

These cover parent-spec §15.1 exit criteria #5 (renders without console errors), #8 (different `dt_sec` channels still align — observable when waveforms and markers visually agree), and #9 (chooser banner + exact-hash lookup — exercised in step 4 / by `runSelection` unit tests). They are not automated.

## 7. Risks and decisions deferred

- **Hand-written types ≠ runtime validation.** A `JSON.parse(...) as Manifest` cast is a no-op at runtime. The fixture-based unit tests in §3.3 catch the *known* shape only — a producer regression that drops a known field surfaces the next time someone refreshes the fixture, but a producer regression that adds a wrong-shaped field on an existing key is silently ignored until it crashes a component. Acknowledged PoC limitation; Zod can be added incrementally without restructuring components.
- **No CSS framework.** Phase 5's edit UI may pull in Tailwind or similar. Plan 2's hand-rolled CSS is throwaway by design.
- **No CI.** Plan 2 doesn't add a GitHub Actions step. The first `pnpm test` is a manual gate.
- **Single video element.** Multi-camera episodes (parent-spec future) will need a video grid. Plan 2 ignores this; `manifest.artifacts[]` only carries one `role: "video"` entry today.
- **No keyboard shortcuts.** Space-to-play, J/K/L scrub, etc. are Phase 5.

## 8. Open items

- The exact set of `supportedMajors` (currently `{ manifest: [1], annotation: [1], boundaries: [1], signals: [1] }`) lives in `lib/manifest.ts` as a constant. When Plan 1's writers bump a major, the viewer must explicitly opt-in (parent-spec §6.6 — set membership, not `>=`). This is fine; it is the only place the viewer encodes its compatibility surface.
- The `BoundaryMarkerLayer` color palette is hard-coded. If parent-spec §5.2 ever adds detector sources (Phase 3 adds `gripper_object_distance_threshold_crossing` and `object_motion_start_stop`), the viewer needs a new color and a fall-back gray for unknowns.

## 9. Plan-2 boundary (what writing-plans will turn into tasks)

Roughly:
1. Scaffold `frontend/` (package.json, tsconfig, vite.config.ts, index.html, main.tsx, App.tsx empty shell, App.css).
2. Implement `lib/manifest.ts` (types + `artifactUrl` + `resolveUrl` + `assertIndexSchema` + `assertConsumerCapability` + `assertArtifactSelfConsistent`) and its tests with a fixture committed from a real `runs/` directory.
3. Implement `lib/runSelection.ts` (pure function for the §4 routing rule) and its tests.
4. Implement `lib/time.ts` and `lib/fetchRetry.ts` with their tests.
5. Implement `RunList` (handles the empty / 4xx / 5xx / unsupported-major paths from §5).
6. Implement `RunViewer` (data fetch wiring + `currentTimeSec` state + `widthPx` `ResizeObserver` + AbortController for URL-change race + `pipeline_status` banner).
7. Implement `VideoPlayer`.
8. Implement `Timeline` + `BoundaryMarkerLayer` (consume `widthPx` prop).
9. Implement `WaveformView` (consume `widthPx` prop; per-channel SVG).
10. Wire compat-mismatch and the rest of the §5 error/loading states.
11. Manual smoke against `lerobot/svla_so100_pickplace` ep0 — verify exit criteria #5, #8, #9 in a browser.
12. `frontend/README.md`: install / dev / test commands. One short file.

The exact granularity (one task or two, ordering, whether to bundle 8+9) is the writing-plans skill's job, not this spec's.
