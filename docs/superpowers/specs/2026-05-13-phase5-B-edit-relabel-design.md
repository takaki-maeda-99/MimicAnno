# Phase 5 B (release 1) — phase relabel edit

Date: 2026-05-13
Status: draft
Author: Claude (Opus 4.7), post autonomy-exit (確認モード)
Sub-project: Phase 5 B (Edit UI) **release 1**: phase relabel only.
Subsequent releases (boundary drag, reviewed flag, object/target, etc.)
ship as separate specs/PRs on top of this foundation.

Related:
- Parent: [`2026-04-25-mimicanno-design-brushup.md`](./2026-04-25-mimicanno-design-brushup.md) §15 #17 (Phase 5 exit criterion), §14 (MimicRec ABI), §4.4 (publish lock)
- Predecessor (read-only HTTP foundation): [`2026-05-12-phase5-A-persistence-backend-design.md`](./2026-05-12-phase5-A-persistence-backend-design.md) — `ETag: "<run_hash>"` on manifest already in place for optimistic concurrency
- Schema: `mimicanno/schema.py::SubtaskSegment`, `mimicanno/configs/labels/manipulation.yaml`

---

## 1. Motivation

Phase 5 A shipped a read-only HTTP backend (`GET /api/runs/*`) and the
viewer renders runs from it. The next blocker for the Phase 5 exit
criterion §15 #17 ("Edit UI persists changes via backend; export to
parquet matches the round-trip schema") is **the human review loop**:
the user inspects mimicanno's auto-labels and needs a way to fix the
wrong ones.

The smallest useful step in that loop is **relabeling a segment's
``phase``** — picking the right label out of the manipulation enum when
Gemma mis-classified. Everything else (boundary timing, object name,
reviewer flag) is a follow-up that builds on the same wiring.

Per user scope decision (2026-05-13): release 1 covers **phase relabel
only**, with tests-first / one-field-at-a-time discipline. Boundary
drag etc. are deferred to release 2+ specs.

## 2. Scope

In scope:
- New endpoint `PATCH /api/runs/<canonical_name>/segments/<segment_id>`
  with body `{"phase": "<label_id>"}` (no other keys accepted in r1)
- New endpoint `GET /api/labelset` — returns the allowed-label list the
  server loaded at startup so the frontend dropdown has a source
  (manifest does NOT carry labelset; per-run labelsets are a future
  addition, see §7)
- `If-Match: "<run_hash>"` precondition; 412 on stale
- Manifest re-emission: writing the segment replaces both
  `annotation.json` (segment's `phase`, `smoothing_ops += ["edited"]`,
  `reviewed=true`, `reviewer_id=<from env>`, top-level
  `run_hash`=new_hash, top-level `generated_at`=preserved) and
  `manifest.json` (`run_hash`=new_hash, `generated_at`=preserved,
  `edited_at`=now). `runs/index.json` row is upserted via the existing
  `runindex.upsert_row` path.
- Schema extensions (writer + reader in lockstep):
  - `SmoothingOp` Literal in `mimicanno/smoother.py:28` gets `"edited"`
  - `_ALLOWED_SMOOTHING_OPS` set + post-init guard in
    `mimicanno/schema.py:133-180` extended in the same commit
  - `Manifest.canonical_name: str` field added. Populated by
    `mimicanno/publish.py` on initial publish (r1 includes this writer
    change, NOT deferred) and preserved by the PATCH writer
- Content-Type enforcement: non-`application/json` bodies → 415
- Reviewer identity: `MIMICANNO_REVIEWER` env var resolved at server
  startup; PATCH attaches it to the segment. Empty env → `reviewer_id`
  stays `null` (existing schema allows null).
- Label validation: target phase must be in the run's labelset; 400
  `invalid_label` otherwise. The labelset is loaded once at server
  startup from `mimicanno/configs/labels/manipulation.yaml` (already
  what `mimicanno annotate` uses).
- Frontend: existing segment row gets a `<select>` for phase. Auto-save
  on change (debounce 200 ms in case of rapid toggles), shows a toast on
  412 stale ("annotation was updated elsewhere — reload to continue").
- Tests: server unit + integration (real on-disk PATCH cycle), plus
  one frontend interaction smoke (vitest + testing-library) for the
  dropdown.

Out of scope (separate specs):
- Boundary drag / time adjust → release 2 (frame-unit snap per scope Q4)
- Explicit `reviewed=true` toggle without changing `phase` → release 3
- `object` / `target` / `verb` / `failure_flags` edits → release 4+
- Authentication / multi-user — Phase 6+
- Re-running the smoother after edits — edits are verbatim, no auto
  re-smoothing (footgun avoidance; the human's choice wins, and
  downstream sees `smoothing_ops` ending in `"edited"`)
- Undo / history beyond the client-side stack — release 5+
- MimicRec integration — sub-project E (will piggyback on the same
  PATCH shape so this spec is forward-compat with E)

## 3. Design

### 3.1 Endpoints

#### PATCH

```
PATCH /api/runs/{canonical_name}/segments/{segment_id}

Request headers:
  If-Match: "<expected run_hash, exact string from prior manifest>"
  Content-Type: application/json     # 415 if absent/different
Request body:
  { "phase": "<label_id>" }     # exactly this one key in release 1

Responses:
  200 OK
    body: the updated manifest.json (so client can refresh its ETag)
    headers: ETag: "<new run_hash>"
  400 invalid_body         missing 'phase' key, extra keys, or non-str value
  400 invalid_label        phase ∉ labelset
  400 invalid_name         canonical_name regex fail (same as A)
  400 invalid_segment      segment_id not in annotation.json
  404 run_not_found
  412 etag_mismatch        If-Match header doesn't equal current run_hash
  415 unsupported_media    Content-Type is not application/json
  428 etag_required        If-Match header missing
  500 internal             unexpected error (no stack leak; logged)
```

Method binding: register as `methods=["PATCH"]` on the same router that
already serves the read endpoints.

#### GET /api/labelset

```
GET /api/labelset

Response 200 (application/json):
  {
    "labels": [
      {"id": "approach_object", "requires_object": true},
      {"id": "idle",            "requires_object": false},
      ...
    ],
    "labels_yaml_sha256": "sha256:..."
  }
  ETag: "<labels_yaml_sha256>"
  Cache-Control: public, max-age=300
```

Source is the labels YAML the server was started with (default:
`mimicanno/configs/labels/manipulation.yaml`, same one
`mimicanno annotate` consumes). Loaded once at `create_app` time;
mutating the YAML on disk does NOT change the response until restart.

Field selection: `id` is the canonical label string used everywhere
(annotation, smoothing, parquet). `requires_object` is what
`mimicanno/labelset.py::Label` (labelset.py:22-26) carries — the
frontend uses it to grey out object-required labels when the segment
has no tracked object. `Label.verbs` is currently unused by this
endpoint; a future release that wants verb-aware UI can widen the
response.
Display text is derived **client-side** from `id` (e.g.
`id.replace("_", " ").replace(/^./, c => c.toUpperCase())`); the server
emits no `display` field because `Label` (labelset.py:25-28) has none
and inventing one would split the source of truth.

### 3.2 File-write semantics

The PATCH executes the following sequence under `runs/index.json.lock`.
Note: this lock only protects the publish dir-replacement window
(`publish.py:128-189`); a concurrent `mimicanno annotate` doing
`write_artifacts` into `.tmp.<pid>/` is unaffected. That's fine — the
concurrent annotate publishes via the same lock at the end, and if our
PATCH lands first the annotate will see a fresh `run_hash` and either
short-circuit-reuse-fail or rewrite (both safe).

1. Acquire `runs/index.json.lock` via `mimicanno.locks.file_lock(
   runs_root / "index.json.lock", timeout_sec=30)`. Same symbol
   `publish.py` uses; we call the public lock helper directly rather
   than going through `publish.upsert_row`.
2. Reread `manifest.json` + `annotation.json` from disk (drop any in-RAM
   cache). Compare `manifest.run_hash` to `If-Match`.
3. If mismatch → release lock, 412 `etag_mismatch`.
4. Mutate the target segment in the parsed `annotation.json`:
   - `phase = <new>`
   - `smoothing_ops.append("edited")` (deduped — if already ending in
     `"edited"`, leave as-is)
   - `reviewed = true`
   - `reviewer_id = <MIMICANNO_REVIEWER or None>` —
     **deliberately overwritten**, not preserved from prior edits.
     Release 1 is single-reviewer by design, so the latest editor's
     identity wins. Release 3+ (multi-reviewer) will revisit this
     (likely keep an edit history list rather than a single
     `reviewer_id`).
   - `overall_confidence` recomputed: the formula from
     `mimicanno.smoother._recompute_confidence` is reused, but applied
     to a freshly-constructed `SubtaskSegment` (the smoother helper
     takes a dataclass instance, not a dict). The plan may choose to
     either (a) reconstruct via `SubtaskSegment(**segment_dict)` +
     `_recompute_confidence(...)` or (b) lift the formula into a small
     shared helper in `mimicanno/schema.py`. Either way the (new
     phase, old vlm_confidence, old boundary_confidence) invariant
     from smoother spec §3.5 still holds. **Boundaries are not
     touched** — only the label.
5. Recompute `config_hash + input_hash` is **NOT** redone (those describe
   the pipeline, not the human edit). Recompute `run_hash`:
   - Adopt a deterministic post-edit derivation:
     ```python
     new_run_hash = "sha256:" + sha256_hex_of_str(
         "edit:" + old_run_hash + ":" + segment_id +
         ":" + new_phase + ":" + (reviewer_id or "")
     )
     ```
     The `"sha256:"` prefix is required by the manifest JSON Schema
     pattern `^sha256:[0-9a-f]{64}$`. `reviewer_id_normalized` is
     **exactly** `(reviewer_id or "")` — empty string for None, no
     literal "null" / "None" / serialization-tax characters. Pinned
     in a test (§5.1 #12).
   - This guarantees a fresh hash per logical edit and is reproducible
     (replaying the same edit yields the same hash, useful for D).
   - **Short-circuit safety vs `mimicanno annotate`**: the auto-pipeline
     constructs `run_hash` via `compose_run_hash(config_hash, input_hash)`
     (`config.py:835`) which is `sha256(config_hash || input_hash)`.
     The edit derivation deliberately prepends the `"edit:"` literal so
     **the SHA-256 input space is disjoint** from the auto-pipeline's.
     Hash collision between an edited run_hash and a future auto-pipeline
     run_hash is therefore restricted to a generic SHA-256 collision
     (negligible). Consequently the publish.py reuse short-circuit
     (`publish.py:99-102`) cannot mistakenly skip publish on an edited
     run — it can only match auto-derived hashes.
5b. **Cross-file field consistency rules** (annotation.json and
   manifest.json both carry top-level `run_hash` + `generated_at`):
   - `annotation.run_hash` ← `new_run_hash` (consistency with manifest;
     spec §6 #1 asserts equality)
   - `annotation.generated_at` ← **unchanged** (it documents pipeline
     production time, identical to manifest's `generated_at`; edit
     time is tracked separately via `manifest.edited_at`)
   - `annotation` has no `edited_at` field in r1 — D can join on the
     manifest via `manifest.canonical_name` when it needs edit time.
     Adding it to annotation.json is a future spec if D's join cost is
     too high.

5c. **`Manifest.to_dict()` fan-out** (schema.py:381-403): extend to
   emit the two new optional fields. When `None`, omit from output —
   keeps existing-on-disk manifest byte-identical until the first
   edit/publish that sets them:
   ```python
   if self.canonical_name is not None:
       out["canonical_name"] = self.canonical_name
   if self.edited_at is not None:
       out["edited_at"] = self.edited_at
   ```
   The conditional-emit pattern matches the precedent set in
   `SmootherConfig.to_dict` (Phase 4 smoother sub-project).

6. **Write order — annotation FIRST, manifest SECOND, index THIRD**,
   each via tmp + atomic `replace()`. Why this order:
   - **Crash between annotation and manifest**: state = "OLD manifest
     (old run_hash) + NEW annotation". A subsequent PATCH with OLD
     If-Match **succeeds** (run_hash matches manifest) and overwrites
     annotation again — converging. A subsequent PATCH with the
     would-be-NEW If-Match **412**s safely.
   - **Crash between manifest and index**: state = "NEW manifest (new
     run_hash) + index still pointing at old run_hash_short". The
     viewer's listing column on `runs/index.json` is now stale but the
     run itself is consistent. Recovery: next PATCH or next
     `mimicanno annotate` re-upserts the row. Documented in §7 risks.
   - Reverse order (manifest first) would leave "NEW manifest with NEW
     run_hash + OLD annotation". Clients see fresh ETag but stale
     content — much harder to detect or recover.
   - r1 explicitly accepts both intermediate states on crash; no
     two-phase commit / journal.
Step 7 below sets `manifest.edited_at` **before** the write in step 6
fires — the ordering in this list is "what's prepared first, written
second"; manifest mutation completes in-memory before step 6's atomic
file replace.

7. (Pre-write mutation) Set `manifest.edited_at = now_iso()`.
   `generated_at` is **NOT** touched — it preserves "the time the
   pipeline produced this run" (auto-pipeline contract from
   `mimicanno/writers.py`). The new `edited_at` field reads as "the
   time of the latest human edit, if any" and is what D's
   `human_edit_time` metric consumes (release 3+). Canonical name does
   NOT change (we keep the original directory; the suffix in the dir
   name is the pre-edit hash and is now historical; see §3.3).
8. Upsert `runs/index.json` row (new `run_hash`, new `run_hash_short`,
   `generated_at` preserved, optional new `edited_at`).
9. Release lock.
10. Return 200 with the new manifest body and `ETag: "<new run_hash>"`.

### 3.3 Why `canonical_name` doesn't change on edit

Phase 5 A's manifest URL contract resolves through `manifest_url` in
`runs/index.json`, which points to the canonical dir. If we changed the
canonical name on every edit, every reader's bookmark would break and
older URLs would 404. Keeping the dir name historical (= pre-edit hash)
is the lesser evil.

**Downside (documented for D)**: `canonical_name` no longer equals
`f"{episode_id}__{run_hash[:12]}"` after an edit. Tools that re-derive
canonical name from current `run_hash` (e.g. naive parquet exporters)
must use `manifest.canonical_name` if present, else fall back to dir
name.

**Writer-side change in r1 (not deferred)**: `Manifest.canonical_name:
str | None = None` field is added to the dataclass in
`mimicanno/schema.py`. `publish.py` populates it on initial publish
(= the `canonical_name_for(...)` it already computes at
`publish.py:88-96`). The PATCH writer preserves it verbatim on
edit-rewrite.

**Reader-side fallback (concrete location)**: existing on-disk
manifests lack the field; `mimicanno/io.py::read_manifest`
(io.py:150-199) is extended so when `raw.get("canonical_name")` is
None, it falls back to `path.parent.name`. The Manifest dataclass
stores the resolved value, so all downstream consumers
(`exports/...`, `runs_repo`) see a non-None string.

**Collision-extended canonical_name round-trip**: `publish.py:88-96`
may pick a longer hash suffix (`RUN_HASH_FALLBACK_PREFIX_LEN`) when
the default 12-hex prefix collides. The PATCH writer preserves the
original `canonical_name` verbatim, so collision-extended names
round-trip correctly. Asserted by §5.1 #18.

**JSON Schema additive**: `mimicanno/jsonschemas/manifest.schema.json`
gets a new optional property `"canonical_name": {"type": ["string", "null"]}`
in the `properties` block, NOT added to `required` — so old manifests
keep validating.

### 3.4 Endpoint co-existence with read routes

In Phase 5 A the artifact route is registered as
`@router.api_route("/api/runs/{name}/{artifact}", methods=["GET","HEAD"])`.
B adds a sibling:
`@router.api_route("/api/runs/{name}/segments/{segment_id}", methods=["PATCH"])`.

Path prefixes don't collide (`/segments/...` vs `/<artifact>`).

**Registration order**: in `make_router`, register the more-specific
PATCH route (`/segments/...`) BEFORE the catch-all artifact route
(`/<artifact>`). This makes FastAPI's matching deterministic — the
PATCH route never gets shadowed.

**405 contract**: PATCH on `/api/runs/<name>/manifest.json` (or any
allow-listed artifact name) must return 405 with `Allow: GET, HEAD`
header. Asserted in test §5.1 #11. Without this, the spec's contract
that PATCH is segment-only would be ambiguous.

### 3.4.1 Error envelope JSON shape

Identical to Phase 5 A (`mimicanno/server/errors.py`):

```json
{ "error": "<code>", "message": "<human-readable>" }
```

All 4xx and 5xx responses from B use the same shape. The error codes
introduced by B are listed in §3.1.

### 3.4.2 CORS

Phase 5 A's `app.py:24` sets `allow_methods=["GET", "HEAD"]`. B
extends this to `allow_methods=["GET", "HEAD", "PATCH", "OPTIONS"]`
(OPTIONS is required for preflight). `allow_headers` extends from
`["*"]` (already permissive in A) — no change needed but spec-pinned
to keep `If-Match` and `Content-Type` accepted.

### 3.5 Frontend changes (release 1 minimum)

- `?api=1` toggle. The toggle MUST be threaded into:
  1. `frontend/src/lib/manifest.ts` (or equivalent fetch helper) —
     switches base URL from `/runs/` to `/api/runs/`.
  2. The list view that fetches `runs/index.json` (`RunList.tsx`) —
     the index.json fetch path must also flip to `/api/runs/index.json`.
  3. The viewer detail component that renders the segment table
     (currently `RunViewer.tsx` per the §A handoff) — gates the
     editable phase dropdown column on `useApi=true`.

  Recommended wiring: a React context `ApiToggleContext` set once at
  the routing layer from `searchParams.get("api") === "1"`, consumed
  by both `lib/manifest.ts` (via a hook) and the viewer.

  Without the toggle, the UI is byte-identical to A's read-only viewer.

- Fetch `/api/labelset` once at app load (when `?api=1`); cache by
  the response's ETag (`labels_yaml_sha256`). Re-fetch only on cache
  miss / server restart.
- Add `phase` column to the segment table row as a `<select>` populated
  from the cached labelset.
- On change (plain `onChange`, no debounce — dropdowns aren't typed)
  → send PATCH with current `manifest.run_hash` as If-Match.
- On 200 → update local state with the response's new manifest +
  refreshed ETag for subsequent edits.
- On 412 → toast "更新が衝突しました。リロードして続行してください" + dropdown reverts to the
  previous value.
- On 4xx other than 412 → toast with the server's `error` code; revert.

### 3.6 reviewer_id resolution

```python
import os
REVIEWER = os.environ.get("MIMICANNO_REVIEWER") or None
```

Resolved once at `create_app` time and **passed in as a parameter**:
`create_app(*, runs_root, cors_origins, reviewer: str | None = None)`.
The CLI (`mimicanno serve`) reads the env var and forwards. Tests
override directly (no environment manipulation in test fixtures).

**Never** read from request headers/body in release 1 — keeping the
surface tight.

If a `.env` file exists in the working dir, the user can `source .env`
before `mimicanno serve`; we do NOT add a python-dotenv dependency for
r1 (one fewer thing to install).

### 3.7 Audit trail

- `segment.smoothing_ops` gets `"edited"` appended (deduped).
  Downstream consumers (D, parquet export) can already render
  `smoothing_ops` so no schema change required.
- `segment.reviewed = true`. `reviewer_id = <env or null>`.
- Server-side `INFO` log per PATCH:
  `edit: <run_hash_old> → <run_hash_new>, segment=<id>, phase=<new>, reviewer=<id>`
- No edit-time-delta tracked in r1 (D's `human_edit_time` is release 3+).

## 4. Backward compatibility

- `[server]` extra still doesn't pull pydantic-models — PATCH bodies are
  validated by hand (FastAPI does this regardless via the function
  signature).
- Read endpoints are byte-identical to A.
- annotation.json shape: existing fields untouched. `smoothing_ops`
  semantics extended (`"edited"` is a new valid op string). spec §1 of
  the smoother already says ops list is "an open enum of strings" —
  no schema bump.
- Adding `canonical_name` to manifest is additive; existing readers
  that ignore unknown fields keep working.

## 5. Test plan

### 5.1 Server unit (`tests/server/test_routes_patch.py`)

Count = 18 (each numbered item is exactly one test).

1. PATCH happy path → 200, new ETag, response body = updated manifest.
   Asserts on disk: annotation.json shows new phase + `"edited"` op +
   `reviewed=true` + reviewer_id; `manifest.canonical_name` preserved
   unchanged; `manifest.run_hash` matches the new ETag (with
   `sha256:` prefix); `generated_at` UNCHANGED; `edited_at` set.
2. If-Match correct → 200 (covered by #1, but kept as a stand-alone
   permutation for the matrix completeness assertion in §6 #3)
3. If-Match stale → 412 `etag_mismatch`
4. If-Match absent → 428 `etag_required`
5. invalid_body: missing `phase` key → 400 `invalid_body`
6. invalid_body matrix (parametrized: extra keys / non-str value /
   empty body / non-JSON syntactic garbage) → each 400 `invalid_body`
7. invalid_label: phase not in labelset → 400 `invalid_label`
8. invalid_segment: segment_id not in annotation → 400 `invalid_segment`
9. invalid_name + run_not_found (re-uses A's regex/repo errors)
10. Content-Type missing or not `application/json` → 415
11. PATCH on `manifest.json` path → 405 with `Allow: GET, HEAD` header
    (FastAPI sets it once routes are registered in the order pinned in
    §3.4)
12. **`reviewer_id` encoding for hash**: with `reviewer=None`, hash
    input substring is `""`; with `reviewer="takaki"`, it's `"takaki"`.
    Two parametrized cases, each asserts the new `run_hash` equals a
    pre-computed hex constant.
13. Concurrent PATCH race using **uvicorn-in-process** (`threading.Thread`
    that runs `uvicorn.Server.run()` against the test app, then 2
    `httpx.Client` PATCHes from the test thread with the same
    If-Match): exactly one 200 + one 412. TestClient-based race is
    explicitly NOT acceptable (synchronous, serializes).
14. `smoothing_ops` dedup: editing a segment that already ends in
    `"edited"` doesn't append a second time
15. PATCH preserves all non-target segments byte-for-byte (load
    annotation.json before & after, JSON-compare every other segment
    deeply)
16. `mimicanno annotate` (no `--force`) run after a PATCH overwrites
    the edit and emits a WARNING. The PATCH-then-annotate sequence is
    asserted: annotate's reuse short-circuit (`publish.py:99-102`)
    does NOT fire because the on-disk `run_hash` is the edit-derived
    one. Asserted at server-test layer by invoking
    `pipeline.annotate_episode(...)` directly on the tmp tree.
17. `GET /api/labelset` returns `labels_yaml_sha256` equal to
    `load_label_set(...).sha256` and `ETag` header equal to that value.
18. **Collision-extended canonical_name round-trip**: synthesize a
    manifest whose `canonical_name` is at the
    `RUN_HASH_FALLBACK_PREFIX_LEN` length (16-hex suffix), PATCH a
    segment, assert the surviving `manifest.canonical_name` is byte-
    identical to the input.

Plus white-box invariants reused as helpers (not separately numbered):
- PATCH does NOT change boundaries, vlm_confidence, smoothing_ops
  entries other than the appended `"edited"`, or any other segment
  field (asserted inside #1 + #15)
- `MIMICANNO_REVIEWER=takaki` → segment's `reviewer_id == "takaki"`;
  unset → `reviewer_id == None` (asserted inside #1 + parametrized #12)

### 5.2 Server integration

- Real `runs/so101_phase4_v5/episode_000000__*` ep, PATCH a segment,
  re-GET manifest.json, ensure new ETag and `annotation.json` content
  match.
- Cycle: PATCH → GET annotation.json shows edit → PATCH again with new
  ETag → succeeds → original ETag now 412s.

### 5.3 Frontend interaction

- vitest + testing-library: render the segment row, change the phase
  dropdown, assert a PATCH was fired with the right body + If-Match
  header.
- 412 path: mock server returns 412, assert toast renders and dropdown
  reverts.
- Keep the test scope at "this one dropdown" — no full app routing.

### 5.4 mypy + regression

- `uv run --extra server mypy mimicanno/server`
- `uv run pytest tests/ -q` (regression)
- `cd frontend && pnpm test` (vitest)

## 6. Exit criteria

1. PATCH happy path round-trips end-to-end against `runs/so101_phase4_v5/`
2. All enumerated test cases green (§5.1 = 18 server unit, §5.2 = 2
   integration, §5.3 = 3 frontend vitest). Total = 23 new tests.
3. Status-code matrix complete: 200 / 400 (×4 sub-codes: `invalid_body`,
   `invalid_label`, `invalid_name`, `invalid_segment`) / 404 / 405 /
   412 / 415 / 428 all assertable and asserted
4. Race test (§5.1 #13) is real-concurrency (uvicorn-in-process), NOT
   `TestClient`. Demonstrates "exactly one of 2 simultaneous PATCH wins"
5. `create_app(reviewer=...)` honored by `serve_cmd` reading
   `MIMICANNO_REVIEWER`; absent → null; pinned reviewer encoding in
   §5.1 #12
6. Existing 1070+ tests green (no regression on read endpoints, on
   annotate pipeline, or on publish-with-canonical_name change). Likely
   affected snapshot/golden tests pre-flighted: `io.py:read_manifest`
   tests (canonical_name added), any manifest fixture goldens
7. `mypy --strict` clean over `mimicanno/server`
8. Frontend manual smoke: open the viewer with `?api=1`, click through
   relabeling 3 segments, refresh the page, edits persist (and the
   detail view shows the new phase + reviewed indicator)
9. JSON schemas still validate fixtures: `mimicanno/jsonschemas/
   manifest.schema.json` updated with optional `canonical_name`,
   existing on-disk manifests (pre-r1) validate without change
10. notes `2026-05-13-phase5-b-r1-results.md` with curl + frontend
    screenshots

## 7. Risks & follow-ups

- **`canonical_name` drift**: edits don't move the dir, so the dir-name
  hash suffix becomes "the hash on first publish, not current". Tools
  that re-derive canonical name from `run_hash` need to use the new
  `manifest.canonical_name` field — flagged in §3.3, documented in B's
  results note.
- **Re-running `mimicanno annotate` after edits will overwrite them**
  unless `--force` is set, because the reuse short-circuit (§4.4 step 2)
  matches on `manifest.run_hash`. After an edit the `run_hash` is no
  longer the auto-computed one, so the short-circuit will *not* fire and
  annotate will rewrite the dir. **This is correct** (auto-pipeline
  re-run replaces human edits — same as if a human ran `mimicanno
  annotate --force` today). Document this in the user-facing README.
- **Server caching**: B introduces an in-flight edit window where two
  GETs straddling a PATCH return different bodies. We rely on
  `Cache-Control: no-cache` (already set in A) so browsers don't show
  stale segments after a refresh.
- **D dependency**: D's `human_edit_time` metric requires per-edit
  timestamps. Release 1 logs `generated_at` on the manifest but doesn't
  keep an edit history. D's spec will revisit whether per-edit history
  needs to live in annotation.json (probably yes, as a `history[]`).
- **MimicRec (E)**: the same PATCH shape is what E's "fix annotation
  from inside Replay" feature will reuse. The contract here (PATCH
  segment, ETag/If-Match, body shape) is the contract E gets — keep it
  stable.

## 8. Implementation order (for the plan)

1. **`smoothing_ops` lockstep (3 sites)**:
   - add `"edited"` to `SmoothingOp` Literal at `mimicanno/smoother.py:28`
   - add `"edited"` to `_ALLOWED_SMOOTHING_OPS` at
     `mimicanno/schema.py:133-135` (widens the set; the ValueError at
     `:178-180` still fires for unknown ops)
   - run existing tests — confirm `"edited"` passes through
2. **Manifest schema fan-out**:
   - add `canonical_name: str | None = None` and `edited_at: str | None
     = None` fields to `Manifest` dataclass in `mimicanno/schema.py`
   - extend `Manifest.to_dict()` (`schema.py:381-403`) to emit the two
     fields **conditionally** (only when non-None) — keeps existing
     on-disk manifests byte-identical until first edit/publish
   - extend `mimicanno/io.py::read_manifest` (io.py:150-199) to:
     `canonical_name = raw.get("canonical_name") or path.parent.name`
     and `edited_at = raw.get("edited_at")` (None when absent)
   - update `mimicanno/jsonschemas/manifest.schema.json` `properties`
     to include `canonical_name` (type: ["string", "null"]) and
     `edited_at` (type: ["string", "null"]), both optional
     (NOT added to `required`)
   - update `publish.py` to populate `canonical_name` on initial
     publish (`canonical_name_for(...)` already computed at
     `publish.py:88-96`)
   - regression test (Manifest fixture in `tests/io/fixtures/` or
     similar — TBD by implementer) confirming existing on-disk
     manifests parse with `canonical_name` falling back to dir name
3. **`mimicanno/server/edit_repo.py`** (new module): pure-Python write
   transaction.
   - acquire `mimicanno.locks.file_lock(runs_root / "index.json.lock",
     timeout_sec=30)`
   - reread manifest + annotation
   - compute new run_hash with `"sha256:" + sha256_hex_of_str(...)`
   - write annotation → manifest → index, each via tmp+replace
   - return new manifest dict for the route to emit
   - No FastAPI imports. ~150 LOC.
4. **`mimicanno/server/labelset.py`** (new module, ~20 LOC):
   load `mimicanno.labelset.load_label_set` once; expose
   `LabelSetCache` for dependency injection.
5. **`mimicanno/server/routes.py`**:
   - register PATCH route at `/api/runs/{name}/segments/{segment_id}`
     **before** the existing `/api/runs/{name}/{artifact}` GET route
     (§3.4 registration order)
   - extend `allow_methods=["GET", "HEAD", "PATCH", "OPTIONS"]` in
     `app.py:24`'s CORS middleware
   - add `GET /api/labelset` route emitting the §3.1 shape
6. **`mimicanno/server/app.py`**: extend `create_app(reviewer:
   str | None = None, ...)` and thread it into the router/repo.
7. **Server unit tests (§5.1, TDD)** — red → green, 17 cases.
8. **Server integration test** (§5.2) against `tmp_runs_root` fixture
   (already in `tests/server/conftest.py` from A; extend if needed).
9. **`mimicanno/cli.py`**: `serve_cmd` learns
   `os.environ.get("MIMICANNO_REVIEWER")` + forwards to `create_app`.
10. **Frontend**: `?api=1` toggle wired into both `lib/manifest.ts`
    (URL base) and the viewer detail component (dropdown gate);
    `/api/labelset` fetch + ETag-keyed cache; phase `<select>` per
    segment row; PATCH client with If-Match handling; 412/4xx toast.
11. **Frontend tests (§5.3)** (vitest + testing-library).
12. **Manual smoke** against `runs/so101_phase4_v5/`.
13. **Docs**: README server section addendum (PATCH + labelset
    endpoints), `mimicanno/server/README.md` extension on the write
    contract + crash-recovery semantics + `?api=1` rollout note.
14. **notes** `2026-05-13-phase5-b-r1-results.md`, memory update.
