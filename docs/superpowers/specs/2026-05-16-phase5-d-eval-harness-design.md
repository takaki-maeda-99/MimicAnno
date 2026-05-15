# MimicAnno Phase 5 D — Evaluation harness design

Status: **draft, rev-2** (B r2/r3 already shipped on main → extend scope).
Author: brainstorming session 2026-05-15.
Supersedes: nothing — new sub-plan.

## Revision log

**rev 2 (2026-05-16, late)** — B r2 (boundary drag, `9c25b87`) and
B r3 (reviewed toggle, `14eb192`) shipped on main AFTER rev1 was written.
Rev2 extends the EditEvent emit surface from the single `edit_repo.apply_edit`
to **all three PATCH write paths** so that history is captured uniformly
regardless of which UI surface produced the edit. Without this extension,
boundary drags and reviewed toggles would invisibly mutate `manifest.run_hash`
+ `manifest.edited_at` but contribute nothing to `annotation.history[]`,
breaking hash-chain integrity (§4.5 `HISTORY_CHAIN_BROKEN`) on any sequence
that mixes phase / boundary / reviewed PATCHes.

Changes vs rev1:

| Item | rev1 | rev2 |
|---|---|---|
| Emit surface | `edit_repo.apply_edit` only | `edit_repo.apply_edit` + `boundary_repo.patch_boundary` + `reviewed_repo.patch_reviewed` |
| Helper | inline `_build_event` in `edit_repo.py` | Shared helper `mimicanno/server/history_event.py::build_event` consumed by all three repos; takes `(field, from_value, to_value, segment_id, ...)` and is field-agnostic |
| `EditEvent.field` actually emitted in r1 | `"phase"` only | `"phase"` / `"boundary"` / `"reviewed"` all live |
| `from_value` / `to_value` type per field | `str | None` (phase) | `str | None` (phase), `int | None` (boundary new_frame), `bool | None` (reviewed) — explicit per-field rules in §2.1 |
| Frontend timing | phase `<select>` focus→change | Same — boundary drag / reviewed toggle timing is **NOT** instrumented in r1 (server-side `server_inter_event_ms` still lands). Client coverage for non-phase events will be 0 by design. Deferred to D r2. |
| `label_agreement` corpus | All `history[]` events | Only `field == "phase"` events (explicit filter in metric definition) |
| `human_edit_time` corpus | All `history[]` events | Same — field-agnostic, sums any duration. boundary/reviewed contribute `server_inter_event_ms` only (client coverage drops; tracked separately in aggregate) |
| `pre_edit_overall_confidence` | First phase event per segment | Same — only set when `field == "phase"`; always `None` for boundary/reviewed events |
| New tests | 27 cases | 27 + 8 = **35 cases** (boundary emit ×2, reviewed emit ×2, mixed chain ×2, client_coverage breakdown ×1, helper unit ×1) |
| Exit criteria | 15 items | 15 + 3 = **18 items** (§6 #16 / #17 / #18) |

Open question deliberately deferred to D r2: should `label_agreement` also
emit a `boundary_agreement_rate` (% of auto boundaries kept vs. dragged)?
For r1 the answer is no — boundary semantics differ from phase (continuous
position vs. discrete label), so the metric is non-trivial. Tracked in §7.

**rev 1 (2026-05-16)** — applied reviewer Blocker + S1 fixes from the
2026-05-15 spec-document-reviewer pass. Changes:

| Reviewer item | Severity | What changed | Section |
|---|---|---|---|
| B1 (test-count miscount) | Blocker | Replaced "18 unit + 2 integration" wording with explicit 5-file PATCH-surface list and accurate count of **38 cases**. Exit criterion #12 now names the files and pins them as the "no-modification" gate. | §6 #12; plan §1, §2, §4 |
| B2 (schema bump unenforced) | Blocker | Acknowledged that `schema_version` has no `enum`/`const` at the schema layer and the loader does not validate the literal. Bump is **declarative**; refusal of unknown versions is enforced **only inside `mimicanno eval --schema-version`**. T3 now starts by pinning the current production literal via a regression test before bumping. | §2.3; plan T3 |
| B3 (atomicity claim contradicts crash window) | Blocker | Replaced the "partial write impossible" claim with a precise scoped invariant ("single-file atomicity preserved; inter-file crash window persists"). Added new warning code `HISTORY_AHEAD_OF_MANIFEST` for the case `history[-1].new_run_hash != manifest.run_hash`. Added server test §5.1 #11 to exercise this via `write_manifest_json` monkeypatch. | §1.1, §3.1, §4.5, §5.1 #11; plan T6.5 |
| S1 (confidence-bucket approximation) | Should-fix | Added `pre_edit_overall_confidence: float \| None` to `EditEvent`, set only on the FIRST `(segment_id, field)` event per run. `_build_event` captures it from the pre-mutation segment snapshot. §4.3 `by_confidence_bucket` rule is now exact (no footnote); falls back to current `segment.overall_confidence` for unedited segments and bucket `"unknown"` for pre-D edited segments. | §2.1, §3.1, §3.2, §4.3 |
| S3 (§7 bias direction typo) | Should-fix | Corrected "biases downward" to "biases upward" with reasoning (idle gap between `generated_at` and reviewer arrival is absorbed up to the 1h clip). Documented why frontend `client_session_started_ms` was rejected for r1. | §7 |
| S5 (body validator vs silent-drop) | Should-fix | Made the contract explicit: **400 on type violation** (non-numeric, list, dict); **silent drop on value-range violation** (NaN, inf, negative, >1h). plan T6 mirrors this in test comments. | §3.3; plan T6 |
| S6 (412 must not grow history) | Should-fix | Added server test §5.1 #12 (independent from B r1 byte-identity test). | §5.1 #12; plan T6.5 |
| S4 (T7 phantom flag) | Should-fix | plan T7 rewrites the "force-reuse" wording — the actual mechanism is invoking `mimicanno annotate` (overwrite path), no such flag exists. | plan T7 |
| S2 (round-trip 3-event chain) | Should-fix | Test coverage added — see plan T8 (3-event chain test in CLI unit set). `by_phase` semantics will be formalized inline in `mimicanno/eval/metrics.py` docstring. | plan T8 |

Remaining items deferred to D r2 (per reviewer N1–N4): pyproject `testpaths` audit (will be verified during T12 instead), `mimicanno.eval` re-export, frontend "rapid back-to-back changes" timing fix, `--strict` flag for hash-chain hard-fail.

Parent spec: [`2026-04-25-mimicanno-design-brushup.md`](./2026-04-25-mimicanno-design-brushup.md)
(§6 schema, §10 phase decomposition, §15.4 Phase 5 exit criteria,
§16 deferred items).
Phase 5 umbrella: [`2026-04-30-mimicanno-phase5-export-design.md`](./2026-04-30-mimicanno-phase5-export-design.md)
(table at §0 — this spec covers row **D. Evaluation harness**).

**Hard dependencies** (load-bearing — fail-loud if violated):
- [`2026-05-12-phase5-A-persistence-backend-design.md`](./2026-05-12-phase5-A-persistence-backend-design.md)
  (server scaffolding, `runs/index.json` shape, error envelope).
- [`2026-05-13-phase5-B-edit-relabel-design.md`](./2026-05-13-phase5-B-edit-relabel-design.md)
  (PATCH semantics, manifest `edited_at`/`canonical_name`,
  `smoothing_ops += ["edited"]`, `reviewer_id`, `label_source = "human_edit"`).
  **This spec extends B's write transaction** by appending an `EditEvent`
  to `annotation.json.history[]` on every PATCH (§3.2). All other B
  invariants are preserved byte-for-byte.

Sibling (parallel, independent): [`2026-05-13-phase5-B-edit-relabel-design.md`](./2026-05-13-phase5-B-edit-relabel-design.md) r2+ (boundary drag, reviewed toggle, object edit). D is forward-compatible with those releases: the `EditEvent` schema in §3.2 accommodates field-level diffs beyond `phase`.

---

## Reviewer context

(For reviewers unfamiliar with the parent spec — skim if you've already read it.)

### What is MimicAnno?

A robot-episode subtask annotator. Phase 1 produces unlabeled boundary skeletons, Phase 2 fills phase labels via Gemma, Phase 3 adds SAM3 + object-aware relabel, Phase 4 smooths. Phase 5 ships a human edit UI + parquet export + evaluation harness on top.

### Where Phase 5 D fits

Phase 5 D is the **closing-the-loop** sub-project. Once humans are editing labels through the Phase 5 B UI, we need to answer two questions empirically:

1. **`human_edit_time`** — how much human time does it cost to review/correct one episode? This is the metric we will use to justify (or reject) the auto-pipeline's value vs. fully-manual labeling. It must be measured on real data, not estimated.
2. **Label-agreement** — how often does the auto-pipeline agree with a human reviewer? Broken down by source (`vlm_robot_state_only` vs `vlm_with_object_state`), by phase, and by confidence bucket. This drives Phase 6 model improvement choices (which auto-labels to trust, which to gate behind low-confidence filters).

### What you should be evaluating

If you're a reviewer, the question is: **could a competent engineering team take this document and produce an implementation that (a) does not regress Phase 5 B's PATCH correctness or atomicity guarantees, (b) emits a `mimicanno eval` report that can be acted on by a human reading it once, (c) gives stable numbers across re-runs over the same edited runs, (d) leaves Phase 5 B r2+ unobstructed (boundary drag, etc.), (e) preserves Phase 1–4 on-disk byte-identity for un-edited runs?**

---

## 0. Scope and intent

In scope:

- **Schema extension** to `annotation.json`: append-only `history: list[EditEvent]` field. Optional, omitted on un-edited runs. Schema-version bumps `annotation.schema.json` minor revision.
- **B-side write contract extension**: `mimicanno/server/edit_repo.py::apply_edit` appends one `EditEvent` per successful PATCH. No new HTTP surface. (B r1 currently does not log history; this spec is what makes B's PATCH observable.)
- **New `mimicanno eval` CLI subcommand**. Reads one or more run directories and emits a per-run + aggregate report.
- **Two metric families** (parent spec §6.5 "evaluation harness `human_edit_time` etc."):
  - `human_edit_time` — per-episode, per-reviewer, per-segment edit-duration estimates.
  - `label_agreement` — per-segment auto-vs-edited comparison: confusion matrix, flip rate, by-source breakdown, by-confidence-bucket breakdown.
- **Output formats**: JSON (machine-readable, schema-versioned) + Markdown summary (human-readable). Both share the same metric structure.
- **Read-only over `runs/`**: `mimicanno eval` is byte-passive — it never touches `runs/*` except to read.
- **Frontend opt-in client-side timer**: a millisecond-precision `edit_duration_ms` that the viewer sends in the PATCH body. The server treats this as an unauthenticated hint, never as ground truth.
- **Server-side fallback timer**: when the client hint is absent or implausible (negative, > 1 hour), fall back to `now - prev_event.ts` clipped to a configurable cap.
- **Tests across 4 layers**: server unit (history append), CLI unit (metric arithmetic on synthetic histories), integration (real PATCH cycle → eval report), regression (existing read endpoints and PATCH round-trip).

Non-goals:

- **No new HTTP endpoint.** `mimicanno eval` is a local CLI over `runs/`. We are not adding `GET /api/eval/*`.
- **No new schema for `runs/index.json`.** The eval report is computed on demand from `runs/<canonical_name>/annotation.json.history[]`.
- **No live dashboard, no Slack/Grafana hook.** Out of scope; can be built on top of the JSON report later.
- **No multi-reviewer arbitration or inter-rater agreement (Cohen's κ).** B currently only carries a single `reviewer_id` per segment. Multi-reviewer comparison requires multiple separate `runs/` trees diffed; deferred to D r2.
- **No anonymization or PII scrubbing.** `reviewer_id` is whatever `MIMICANNO_REVIEWER` env was set to at PATCH time; the eval report carries it verbatim. Operators should not put PII in that env var (documented in CLI help).
- **No retroactive edit-time imputation.** Runs edited before this spec ships (so `history[]` is empty but `edited_at` is set) get `human_edit_time = None` and a warning row in the report.
- **No edits-from-replay flow.** Sub-project E (MimicRec integration) will emit its own `label_source = "human_edit"` writes; D is robust to whichever surface (UI or Replay) originated the edit, but doesn't differentiate them in r1.
- **No boundary-drag time tracking yet.** Boundary edits land in B r2; their `EditEvent` shape is reserved in §3.2 but the metric implementation is deferred to D r2.

---

## 1. Reuse and constraints

### 1.1 Where D plugs into existing code

| Existing surface | D's relationship |
|---|---|
| `mimicanno/server/edit_repo.py::apply_edit` (B r1) | **Extended in-place**: append one `EditEvent` with `field="phase"` via the shared helper (below) inside the existing write transaction, between the segment mutation and the `write annotation → manifest → index` ordering. No new lock. No new file. |
| `mimicanno/server/boundary_repo.py::patch_boundary` (B r2, shipped `9c25b87`) | **Extended in-place** (rev2): append one `EditEvent` with `field="boundary"`, `from_value=old_boundary_frame: int`, `to_value=new_frame: int`. Same insertion point pattern as `apply_edit` — between segment mutation (`replace(left, ...)`) and the `replace(annotation, segments=..., run_hash=..., history=...)` construction. |
| `mimicanno/server/reviewed_repo.py::patch_reviewed` (B r3, shipped `14eb192`) | **Extended in-place** (rev2): append one `EditEvent` with `field="reviewed"`, `from_value=old_reviewed: bool`, `to_value=new_reviewed: bool`. Same pattern. |
| `mimicanno/server/history_event.py` (new, rev2) | **New helper module** with `build_event(...)` and `_validate_client_duration(...)`. All three repos call this single function. Replaces rev1's `_build_event` inline in `edit_repo.py`. Pure function — takes `(annotation_history, manifest_generated_at, field, from_value, to_value, segment_id, reviewer_id, prev_run_hash, new_run_hash, client_edit_duration_ms, pre_edit_overall_confidence)` and returns an `EditEvent`. |
| `mimicanno/server/write_txn.py` (shipped) | **Unchanged.** History append happens inside the caller (each `*_repo` mutates `annotation.history` before passing to `write_run_atomically`). `write_txn` itself is content-agnostic. |
| `mimicanno/schema.py::AnnotationResult` | **Schema bump**: add `history: list[EditEvent] = field(default_factory=list)` field, conditionally emitted from `to_dict()` (omit when empty to preserve on-disk byte identity for un-edited runs). |
| `mimicanno/jsonschemas/annotation.schema.json` | **Additive**: declare `history` optional, item schema defined with `field` as one-of `["phase", "boundary", "reviewed"]` (forward-extension to `["object", "verb", "target"]` is a value-set change without schema bump). `schema_version` bumps to next minor (B r1/r2/r3 didn't bump — D does). |
| `mimicanno/cli.py` | **New subcommand**: `mimicanno eval` (~30 LOC of arg parsing + dispatch). |
| `mimicanno/eval/` (new sub-package) | **All eval logic** lives here, fully separable from `server/`, `exports/`, `pipeline.py`. |
| Frontend (`?api=1` edit dropdown) | **Additive**: track focus-in/focus-out timestamps on the phase `<select>`, send `client_edit_duration_ms` in PATCH body. Server-validated (clamp + fallback). Boundary drag (B r2) and reviewed toggle (B r3) do **NOT** capture client durations in r1 — server-side `server_inter_event_ms` is the only timing source for those events. |

Hard constraints inherited from parent spec / B:

- **Atomicity, scoped** (B §3.5 §4.4): each of `annotation.json`, `manifest.json`, `index.json` is written via tmp+rename inside the existing file lock, so a partial **single-file** write cannot be observed. However the **inter-file** crash window documented at `mimicanno/server/edit_repo.py:13-16` ("Crash between annotation and manifest leaves OLD manifest + NEW annotation") **persists under D**: a crash between the `annotation.json` write (now including the new history entry) and the `manifest.json` write will leave on disk a state where `annotation.history[-1].new_run_hash != manifest.run_hash`. This is a new observable consequence of D and is acknowledged here — see §4.5 `HISTORY_AHEAD_OF_MANIFEST` for the warning code and §5.1 #11 for the test. The single-file atomicity invariant (segment + history land together inside annotation.json, or neither) is preserved.
- **`run_hash` derivation** (B §3.5 step 5): the new `run_hash` is `sha256("edit:" + old_run_hash + ":" + segment_id + ":" + new_phase + ":" + (reviewer or ""))`. D does **not** change this formula — the history entry is recorded *after* the new hash is computed and carries both old and new hash for traceability, but does not feed into the hash itself. (Reasoning: hashing history would make hashes path-dependent on edit order, which breaks B §3.5 "fresh hash per logical edit and is reproducible".)
- **B r1 byte-passthrough tests** (B §5.1 #15): "PATCH preserves all non-target segments byte-for-byte." This is unaffected — `history[]` is at the top level of `annotation.json`, not under any `segments[i]`.
- **CLI exit code idiom** (parent §15.4): error envelope `{error: <code>, message: <human>}`; success path emits structured stdout + exits 0.

### 1.2 What MUST NOT change

- `manifest.json` shape (B r1 already extended `canonical_name`, `edited_at`). D does not add manifest fields.
- B's PATCH HTTP contract (request body, response body, headers, status codes, error codes). The only PATCH body addition is **optional** `client_edit_duration_ms: float` — when absent, server behavior is identical to B r1.
- Read endpoints (Phase 5 A). The `GET /api/runs/{name}/annotation.json` already returns whatever's on disk, so a populated `history[]` is naturally visible — no route change needed.
- `runs/index.json` shape.
- `mimicanno annotate` re-run behavior. (Auto-pipeline re-runs replace human edits — same as B r1. The `history[]` is lost on annotate-overwrite, by design. If the operator wants to preserve history they must use `mimicanno annotate --force-reuse` or similar; out of scope.)

---

## 2. Data model

### 2.1 `EditEvent`

```python
@dataclass
class EditEvent:
    # Identity
    event_id: str               # uuid4 hex, 32 chars
    ts: str                     # ISO8601 with timezone, UTC, microsecond precision

    # What
    segment_id: str             # subject of the edit
    field: Literal["phase", "boundary", "reviewed", "object", "verb", "target"]
    # D r1 (rev2) emits "phase" (B r1), "boundary" (B r2), "reviewed" (B r3).
    # Future fields ("object", "verb", "target") are reserved without schema bump.
    from_value: str | int | bool | None
    to_value:   str | int | bool | None
    # Per-field type table:
    #   field="phase"    → str | None         (the old/new phase label; None during early-stage segments)
    #   field="boundary" → int | None         (the old/new start_frame; None never in practice)
    #   field="reviewed" → bool               (the old/new reviewed flag)
    #   field="object"   → str | None         (reserved; future B r4)
    # Loader does not coerce — writer must produce the correct python type.
    # For field="boundary", `segment_id` is the right segment's id (segment whose
    # start_frame was moved), matching B r2's `patch_boundary` `boundary_id` semantics.

    # Who
    reviewer_id: str | None     # from MIMICANNO_REVIEWER at PATCH time

    # Hash provenance
    prev_run_hash: str          # the run_hash this edit started from (= If-Match value)
    new_run_hash: str           # the run_hash this edit produced

    # Timing
    client_edit_duration_ms: float | None
    # Best-effort millisecond duration reported by the editor UI.
    # Validation rules in §3.3. None when the client didn't send one.
    server_inter_event_ms: float | None
    # Wall-time since the previous EditEvent in this annotation's history (or
    # since manifest.generated_at when history is empty). Always populated by
    # the server. Capped at 3600_000 (1 hour) — anything longer is clipped
    # and a `clipped=true` flag is recorded.
    clipped: bool               # true iff server_inter_event_ms was clipped

    # Pre-edit provenance (S1 reviewer fix)
    pre_edit_overall_confidence: float | None
    # The `segment.overall_confidence` value as it stood JUST BEFORE this edit
    # was applied. Set only on the FIRST EditEvent per (segment_id, field)
    # pair within a run's history — subsequent events for the same segment
    # carry None. Captured by `_build_event` (§3.2) from the old segment
    # snapshot before mutation, so the eval CLI's `by_confidence_bucket`
    # metric (§4.3) can bucket by exact pre-edit confidence instead of the
    # post-edit recomputed value. Optional — None when the field semantics
    # don't apply (e.g., non-phase edits, or for segments whose pre-edit
    # confidence is itself None).
```

### 2.2 Where it lives

Appended to `AnnotationResult.history`, which is a top-level list in `annotation.json` ordered chronologically (oldest first). Mutations never reorder, never delete — only append. (Re-running `mimicanno annotate` *replaces* the whole annotation.json, including dropping `history[]`. This is documented and intended; see §1.2.)

### 2.3 Schema versioning

`annotation.schema.json::schema_version` bumps from the current baseline literal (read from real on-disk `annotation.json` files as part of T3 — must be pinned before the bump lands) to **v2.0** (additive minor; loader-compatible per parent spec §6.6). Consumers without v2 awareness see `history[]` as an unknown field and ignore it (Python dataclass loader uses `**kwargs` filter — already wired in `mimicanno/io.py::read_annotation` for forward compat).

**Enforcement note (B2 reviewer fix)**: `annotation.schema.json` currently types `schema_version` as a bare `string` with no `enum` or `const`, and `mimicanno/io.py::read_annotation_result` (`:226`) does not validate the literal. Therefore the bump is **declarative only at the schema layer** — neither writer nor loader will reject a wrong literal in production. The "refuse v3" promise is enforced **inside `mimicanno eval`** via `--schema-version` (default: accept `v2.x`, reject everything else with `EVAL_SCHEMA_INCOMPATIBLE`). T3 must include a regression test that opens a representative production `annotation.json` (e.g. from `runs/so101_phase4_v5/`), asserts the current `schema_version` literal, and pins it; the bump in T2/T3 then changes this literal at exactly one production-writer site (`AnnotationResult.schema_version` default in `mimicanno/schema.py`). Loader-side enforcement is out of scope for D r1; deferred to a future cross-cutting schema-pinning pass.

### 2.4 Conditional emit (un-edited byte identity)

`AnnotationResult.to_dict()` emits `history` only when `len(history) > 0`. Existing un-edited runs continue to write byte-identical `annotation.json` files. Regression test: re-publishing a fresh Phase 4 run produces a JSON whose bytes match the pre-D baseline.

---

## 3. The write extension (B-side change)

### 3.1 Where the change lands

**Three functions** (rev2), all calling a single shared helper:

- `mimicanno/server/edit_repo.py::apply_edit` (B r1) — emits `field="phase"`
- `mimicanno/server/boundary_repo.py::patch_boundary` (B r2) — emits `field="boundary"`
- `mimicanno/server/reviewed_repo.py::patch_reviewed` (B r3) — emits `field="reviewed"`

The shared helper `mimicanno/server/history_event.py::build_event` (new, rev2) replaces rev1's inline `_build_event`. All three repos call it just before constructing the new `AnnotationResult` (via `replace(annotation, ..., history=annotation.history + [event])`). Insertion is between segment mutation and `write_run_atomically` — i.e., within the existing file lock, after `if_match` validation, before the tmp+rename write.

Pseudocode for `apply_edit` (rev2 — additions marked with **D:**, rev1 inline `_build_event` replaced by helper call):

```python
def apply_edit(*, runs_root, name, segment_id, new_phase, if_match,
               reviewer, labelset, client_edit_duration_ms=None):  # D: kwarg added
    with file_lock(runs_root / "index.json.lock", timeout_sec=30):
        manifest = read_manifest(...)
        annotation = read_annotation(...)
        if manifest.run_hash != if_match:
            raise EtagMismatch(...)
        if new_phase not in labelset:
            raise InvalidLabel(...)
        segment = find_segment(annotation, segment_id)
        if segment is None:
            raise InvalidSegment(...)

        # B r1 existing mutation
        old_phase = segment.phase
        old_overall_confidence = segment.overall_confidence   # D: capture for S1
        segment.phase = new_phase
        segment.label_source = "human_edit"
        segment.reviewer_id = reviewer
        segment.reviewed = True
        if "edited" not in segment.smoothing_ops:
            segment.smoothing_ops.append("edited")
        segment.overall_confidence = _recompute_confidence(segment)

        new_run_hash = _derive_edit_hash(manifest.run_hash, segment_id,
                                         new_phase, reviewer)

        # D: history append
        event = _build_event(
            segment_id=segment_id,
            field="phase",
            from_value=old_phase,
            to_value=new_phase,
            reviewer_id=reviewer,
            prev_run_hash=manifest.run_hash,
            new_run_hash=new_run_hash,
            client_edit_duration_ms=client_edit_duration_ms,
            prior_history=annotation.history,
            prior_generated_at=manifest.generated_at,
            pre_edit_overall_confidence=old_overall_confidence,  # D: S1
        )
        annotation.history.append(event)

        manifest.run_hash = new_run_hash
        manifest.edited_at = event.ts            # already in B r1, reused

        write_annotation_atomic(annotation)
        write_manifest_atomic(manifest)
        update_index_atomic(runs_root, name, manifest)
        return manifest.to_dict()
```

### 3.2 `build_event` (shared helper — `mimicanno/server/history_event.py`)

Rev2: extracted from `edit_repo.py` to `history_event.py` so all three repos
import it. Signature is **field-agnostic** — caller supplies `field`,
`from_value`, `to_value`, and (for `field="phase"` only) `pre_edit_overall_confidence`.
Callers from `boundary_repo` / `reviewed_repo` pass `pre_edit_overall_confidence=None`.

```python
def build_event(*, segment_id, field, from_value, to_value, reviewer_id,
                prev_run_hash, new_run_hash, client_edit_duration_ms,
                prior_history, prior_generated_at,
                pre_edit_overall_confidence) -> EditEvent:
    ts = datetime.now(UTC).isoformat(timespec="microseconds")

    # server-side inter-event ms
    if prior_history:
        prev_ts = datetime.fromisoformat(prior_history[-1].ts)
    else:
        prev_ts = datetime.fromisoformat(prior_generated_at)
    delta_ms = (datetime.fromisoformat(ts) - prev_ts).total_seconds() * 1000

    clipped = False
    SERVER_INTER_EVENT_CAP_MS = 3_600_000  # 1 hour
    if delta_ms > SERVER_INTER_EVENT_CAP_MS:
        delta_ms = SERVER_INTER_EVENT_CAP_MS
        clipped = True
    if delta_ms < 0:                       # clock skew / DST oddity
        delta_ms = 0
        clipped = True

    # validated client duration
    cdur = _validate_client_duration(client_edit_duration_ms)

    # S1: only the FIRST phase event per segment carries pre_edit_overall_confidence
    is_first_phase_event_for_segment = not any(
        e.segment_id == segment_id and e.field == field for e in prior_history
    )
    pec = pre_edit_overall_confidence if is_first_phase_event_for_segment else None

    return EditEvent(
        event_id=uuid4().hex,
        ts=ts,
        segment_id=segment_id,
        field=field,
        from_value=from_value,
        to_value=to_value,
        reviewer_id=reviewer_id,
        prev_run_hash=prev_run_hash,
        new_run_hash=new_run_hash,
        client_edit_duration_ms=cdur,
        server_inter_event_ms=delta_ms,
        clipped=clipped,
        pre_edit_overall_confidence=pec,
    )
```

### 3.3 Client duration validation

```python
def _validate_client_duration(v: float | None) -> float | None:
    if v is None:
        return None
    if not isinstance(v, (int, float)):
        return None      # silently drop garbage; server-side is authoritative anyway
    if math.isnan(v) or math.isinf(v):
        return None
    if v < 0:
        return None      # negative duration = clock skew, drop
    if v > 3_600_000:    # > 1 hour per edit; user walked away, untrustworthy
        return None
    return float(v)
```

We **silently drop** invalid client durations rather than 400-ing. Rationale: client duration is a metric hint, not contract data. Dropping is safer than failing the PATCH and confusing the editor user. Server-side `server_inter_event_ms` still lands.

### 3.4 PATCH body schema extension

Only the **phase** PATCH endpoint accepts `client_edit_duration_ms` in r1
(rev2 unchanged from rev1 here). B r2 boundary drag and B r3 reviewed
toggle bodies are **not** extended — those events get `client_edit_duration_ms=None`
on the server side. Their `server_inter_event_ms` still lands.

Endpoint | Body (rev2) | `client_edit_duration_ms` accepted?
---|---|---
`PATCH /api/runs/{name}/segments/{seg_id}/phase` (B r1) | `{ "phase": "...", "client_edit_duration_ms"?: float }` | yes
`PATCH /api/runs/{name}/boundaries/{bnd_id}` (B r2) | `{ "new_frame": int }` (unchanged) | no
`PATCH /api/runs/{name}/segments/{seg_id}/reviewed` (B r3) | `{ "reviewed": bool }` (unchanged) | no

`client_edit_duration_ms` on the phase endpoint is optional. Body validation
accepts (a) `phase` only, (b) `phase` + `client_edit_duration_ms`. Other keys
→ 400 `invalid_body` (B r1 invariant preserved). Boundary/reviewed body
schemas reject any extra keys including `client_edit_duration_ms` (current
behavior is preserved — extending those is a D r2 task).

### 3.5 Front-end timing instrumentation

Add a hook to the phase `<select>` in the viewer detail component:
- `focusin`: store `t0 = performance.now()`.
- `change`: capture `t1 = performance.now()`, send PATCH with `client_edit_duration_ms = t1 - t0`.
- `focusout` without change: discard `t0`.

This is "time the dropdown was open until choice was committed." Coarse, but actionable. Refinements (mouse-down to mouse-up, dwell on options, retries) are out of scope for D r1.

**Boundary drag / reviewed toggle (rev2): no client timing in r1.** The
boundary drag UI in `BoundaryDragLayer.tsx` could capture pointer-down to
pointer-up duration, and the reviewed toggle could capture click event
time, but neither is implemented in D r1. Reason: scope control — phase
edits dominate review time in practice (per smoke estimates), and r2 can
add boundary/reviewed timing without changing the server contract (the
helper is already field-agnostic). r1 server-side `server_inter_event_ms`
covers gross timing for those events.

### 3.6 Error model

No new error codes. Invalid `client_edit_duration_ms` is silently dropped (§3.3). All other PATCH error codes from B r1 unchanged.

---

## 4. The eval CLI

### 4.1 Surface

```
mimicanno eval [RUNS_PATH ...]
               [--reviewer <id>]
               [--phase-filter <phase>]
               [--source-filter <label_source>]
               [--format json|markdown|both]
               [--out <path>]
               [--include-clipped]
               [--schema-version <v>]
```

- `RUNS_PATH ...`: one or more (a) `runs/` roots — recurses one level to find canonical-name dirs; or (b) explicit `runs/<canonical_name>/` dirs. At least one required.
- `--reviewer`: filter events by `reviewer_id` (exact match). Default: all.
- `--phase-filter`, `--source-filter`: restrict the corpus before computing metrics.
- `--format`: default `markdown` to stdout when no `--out`; default `both` (writing `.json` and `.md` side-by-side) when `--out` is given.
- `--out`: prefix for output files. With `--format both`, writes `<out>.json` and `<out>.md`. With single format, writes `<out>.<ext>` literally.
- `--include-clipped`: include events with `clipped=true` in `human_edit_time`. Default false (clipped events count toward agreement but not timing).
- `--schema-version`: pin acceptable `schema_version` prefix. Default: any v2.x. Refuses v1.x (B r1) with a clear message — "edited before D shipped, no history available, re-edit to populate".

### 4.2 What the report contains

JSON shape (canonical structure):

```json
{
  "schema_version": "mimicanno_eval.v1",
  "generated_at": "2026-05-15T12:34:56.789012+00:00",
  "mimicanno_version": "<from mimicanno.__version__>",
  "inputs": {
    "runs_paths": ["..."],
    "filters": {"reviewer": null, "phase": null, "source": null},
    "include_clipped": false
  },
  "summary": {
    "runs_total": 42,
    "runs_edited": 31,
    "runs_with_history": 28,
    "runs_pre_D_warning": 3,
    "total_edits": 187,
    "unique_reviewers": ["takaki", null]
  },
  "human_edit_time": {
    "per_run": [
      {
        "canonical_name": "...",
        "episode_id": "...",
        "edit_count": 7,
        "total_ms_client": 23410.2,
        "total_ms_server": 31204.6,
        "median_ms_per_edit_client": 2870.0,
        "p95_ms_per_edit_client": 9012.5,
        "missing_client_durations": 1,
        "clipped_events": 0
      }
    ],
    "aggregate": {
      "total_ms_client": 312410.2,
      "total_ms_server": 412204.6,
      "median_ms_per_edit_client": 2120.0,
      "p95_ms_per_edit_client": 11020.0,
      "missing_client_durations": 12,
      "clipped_events": 2,
      "client_coverage": 0.93,
      "client_coverage_by_field": {
        "phase": 0.97,
        "boundary": 0.0,
        "reviewed": 0.0
      }
    }
  },
  "label_agreement": {
    "confusion_matrix": {
      "rows": ["<auto phase A>", "..."],
      "cols": ["<edited phase>", "..."],
      "counts": [[12, 1, 0], [0, 8, 2], ...]
    },
    "by_source": {
      "vlm_robot_state_only": {"agree": 31, "disagree": 12, "agreement_rate": 0.72},
      "vlm_with_object_state": {"agree": 88, "disagree": 9, "agreement_rate": 0.91}
    },
    "by_confidence_bucket": {
      "[0.0,0.3)": {"agree": 2, "disagree": 14},
      "[0.3,0.7)": {"agree": 14, "disagree": 6},
      "[0.7,1.0]": {"agree": 103, "disagree": 1}
    },
    "by_phase": {
      "<phase>": {"flips_out": 3, "flips_in": 1, "stable": 22}
    }
  },
  "warnings": [
    {"code": "PRE_D_RUN", "canonical_name": "...", "message": "edited_at set but no history[]; pre-D edit, skipped in timing"}
  ]
}
```

Markdown is a templated rendering of the same — top-level summary, two tables (per-run human_edit_time + by-source agreement), and a section per warning. Lines wrap at 100 chars.

### 4.3 Metric definitions (precise)

**Field-scope rules (rev2):**
- `human_edit_time` aggregates over **all** event fields (`phase`, `boundary`, `reviewed`). `server_inter_event_ms` lands for every event regardless of field. `client_edit_duration_ms` lands only for `phase` events in r1 (§3.5) — `client_coverage` will naturally drop in proportion to non-phase events. The aggregate report breaks coverage out into `client_coverage_by_field` (added in rev2 §4.2) so operators can see this.
- `label_agreement` filters to `field == "phase"` events **only**. Boundary moves and reviewed toggles do not change the segment's `phase`, so they have no first-edit auto-label to compare against. Including them would silently dilute the agreement rate. Filter is applied before `confusion_matrix` / `by_source` / `by_confidence_bucket` / `by_phase` computation. The implementation must assert this filter at the top of `compute_label_agreement(...)`.

**`human_edit_time.per_run.total_ms_client`** = sum of `client_edit_duration_ms` over events with that event's `clipped=false` and a non-null client duration. Events with null client duration contribute 0 and increment `missing_client_durations`.

**`human_edit_time.per_run.total_ms_server`** = sum of `server_inter_event_ms`. The first event in a run's history measures from `manifest.generated_at` (i.e., "time since pipeline completed"). This is biased upward for the first edit, but pinning to `generated_at` is the only causal anchor we have. Documented in CLI help.

**`label_agreement.confusion_matrix`**: rows = the segment's "auto phase" at the time of the **first** `field=="phase"` event in `history[]` (i.e., `event.from_value` of the earliest phase edit per segment); cols = the segment's final phase on disk (`segment.phase`). Segments never edited contribute to the diagonal (auto = final = same phase) iff `label_source != "human_edit"`; segments edited contribute to the appropriate off-diagonal cell. **Note**: a segment edited and then edited back to the original phase contributes to the diagonal with the original auto-source's row (round-trip cancels out in this metric — intentional, we measure "was the auto label correct," not "was the human's first guess correct").

**`label_agreement.by_source.<src>.agreement_rate`** = `agree / (agree + disagree)`. Bucketed by the segment's `label_source` field **as it exists now on disk** — for human-edited segments that's `"human_edit"`, so they appear in a synthetic bucket: agreement is defined as "first auto label == final label" (i.e., `event.from_value` of first phase edit == `segment.phase`). The "human_edit" bucket therefore measures "agreement of pre-edit auto label, given that a human chose to look at this segment." Rows for `vlm_robot_state_only` / `vlm_with_object_state` cover segments the human never edited (so they remain that source).

**`label_agreement.by_confidence_bucket`**: bucketing key = pre-edit `overall_confidence`, sourced as follows:
- For an **edited** segment: `history[0].pre_edit_overall_confidence` where `history[0]` is the earliest event with `field == "phase"` and matching `segment_id` (set by `_build_event` per §3.2 / S1).
- For an **unedited** segment: the on-disk `segment.overall_confidence` (no edit ever happened, so this equals the pre-edit value by construction).
- Segments with `pre_edit_overall_confidence is None` AND no other source (e.g., pre-D-shipped edited segments with empty history) → bucket `"unknown"`.

### 4.4 Algorithm

```
events_by_run = defaultdict(list)
segments_by_run = defaultdict(dict)
for run_dir in resolve(runs_paths):
    manifest = read_manifest(run_dir)
    annotation = read_annotation(run_dir)
    if not annotation.history and manifest.edited_at:
        warnings.append({"code": "PRE_D_RUN", ...})
        continue
    events_by_run[run_dir.name] = annotation.history
    segments_by_run[run_dir.name] = {s.segment_id: s for s in annotation.segments}

# human_edit_time: trivial reduction over events
# label_agreement: walk each segment, look up first phase event per segment_id
```

Complexity: O(total_events + total_segments). Memory: O(largest run's annotation). No cross-run state required.

### 4.5 Sources of error / fail-loud rules

- **`schema_version` mismatch** (annotation.json) → hard error per run with `EVAL_SCHEMA_INCOMPATIBLE`, abort the run, continue with others. Aggregate report still emitted.
- **`history[i].new_run_hash != history[i+1].prev_run_hash`** → hash chain broken; warn but don't abort (could be from a manual edit by a tool we don't know about). Mark the run with `HISTORY_CHAIN_BROKEN` warning.
- **`history[]` non-empty but `manifest.edited_at` missing** → write transaction was buggy; warn `HISTORY_WITHOUT_MANIFEST_TS`, still process.
- **`history[-1].new_run_hash != manifest.run_hash`** (B3 reviewer fix) → inter-file crash window observed: annotation.json + history landed, but the subsequent manifest.json write was interrupted before the new run_hash was persisted. Warn `HISTORY_AHEAD_OF_MANIFEST`, still process (use `history[-1].new_run_hash` for chain checks but trust `manifest.run_hash` as the canonical hash for ETag/PATCH). Recovery is best-effort: the next successful PATCH will rebuild a coherent state (it computes `new_run_hash` from `manifest.run_hash` regardless, and appends a fresh history entry whose `prev_run_hash` matches the stale manifest — the chain will look broken at that boundary, which is correct and observable).
- **Event with `segment_id` not present in `annotation.segments`** → segment deleted post-edit (B r1 doesn't allow this, but a future release might). Skip with warning `EVENT_ORPHANED`.

None of these are CLI exit-code-1 errors unless **zero** runs were processable.

---

## 5. Tests

### 5.1 Server unit (`tests/server/test_edit_history.py`) — new file, ~10 cases

1. PATCH with no `client_edit_duration_ms` → history has 1 event, `client_edit_duration_ms is None`, `server_inter_event_ms > 0`.
2. PATCH with valid `client_edit_duration_ms=1234.5` → event records 1234.5.
3. PATCH with `client_edit_duration_ms=-5` → silently dropped; event records None.
4. PATCH with `client_edit_duration_ms=99999999` (> 1h) → silently dropped; event records None.
5. PATCH with `client_edit_duration_ms="hello"` → 400 `invalid_body` (body schema rejects non-numeric).
   Note: §3.3 says drop; this case is the *body validator* rejecting before duration validation runs. Documented in test.
6. Two PATCHes in sequence → history has 2 events, second event's `prev_run_hash == first event's new_run_hash`, hash chain intact.
7. Server-side `server_inter_event_ms` clipping: monkeypatch `_build_event`'s clock to make delta > 1h → `clipped=true`, `server_inter_event_ms == 3_600_000`.
8. First PATCH on a freshly-published run → `server_inter_event_ms` measured from `manifest.generated_at` (not from None).
9. PATCH that doesn't change phase (re-PATCH same value) → still appends an event (we don't dedup on no-op; up to the eval CLI to filter). `from_value == to_value` event is allowed.
10. Conditional emit: a fresh `annotate` run produces `annotation.json` with **no** `history` key on disk (byte-identical to pre-D). Asserted by `"history"` not in JSON keys.
11. **`HISTORY_AHEAD_OF_MANIFEST` recovery** (B3 reviewer fix): monkeypatch `write_manifest_json` to raise after `write_annotation_atomic` completes → assert annotation.json has new history entry but manifest still carries old `run_hash`. Then call `mimicanno eval` on the run dir → assert warning `HISTORY_AHEAD_OF_MANIFEST` emitted, report still generated.
12. **412 must not grow history** (S6 reviewer fix): PATCH with stale `If-Match` → 412 → reload `annotation.json` → assert `len(history)` unchanged from before the PATCH. Independent of the byte-identity assertion in B r1 `test_apply_edit_stale_etag_raises_and_disk_untouched`, so survives any B r2 formatting churn.
13. **(rev2)** `patch_boundary` history emit: PATCH `/boundaries/{id}` succeeds → annotation.json `history[-1]` has `field="boundary"`, `from_value=<old start_frame>`, `to_value=<new_frame>`, `segment_id=<right segment id>`, `client_edit_duration_ms is None`, `pre_edit_overall_confidence is None`.
14. **(rev2)** `patch_boundary` 412 must not grow history: stale `If-Match` → 412 → `len(annotation.history)` unchanged.
15. **(rev2)** `patch_reviewed` history emit: PATCH `/segments/{id}/reviewed` succeeds → `history[-1]` has `field="reviewed"`, `from_value=<old bool>`, `to_value=<new bool>`, `client_edit_duration_ms is None`, `pre_edit_overall_confidence is None`.
16. **(rev2)** `patch_reviewed` `ReviewedNoChange` (400 no_change) must not grow history: PATCH with same reviewed value → 400 → `len(annotation.history)` unchanged.
17. **(rev2)** **Mixed-field chain** in single test: phase PATCH → boundary PATCH → reviewed PATCH → `len(history) == 3`, fields = `["phase", "boundary", "reviewed"]`, hash chain intact (`history[i].new_run_hash == history[i+1].prev_run_hash`).
18. **(rev2)** **`build_event` unit test** (`tests/server/test_history_event.py`): pure-function call → all branches of `_validate_client_duration` + `pre_edit_overall_confidence` first-event detection + clipping. Decouples helper logic from any specific repo.

### 5.2 Server integration (`tests/server/test_edit_history_integration.py`) — 3 cases

1. Real `tmp_runs_root_loadable` (from B r1) → 3 PATCHes (1 phase + 1 boundary + 1 reviewed) → eval CLI invoked programmatically → JSON report has `total_edits == 3`, `client_coverage_by_field` shows ~1.0 for phase and 0.0 for boundary/reviewed, `label_agreement.confusion_matrix` reflects only the phase edit (boundary/reviewed filtered).
2. PATCH-then-`mimicanno annotate --force` → `annotation.json` rewritten without history, eval CLI reports `runs_with_history -= 1`.
3. Hash-chain integrity: tamper with `annotation.history[1].prev_run_hash` to break the chain → `mimicanno eval` emits `HISTORY_CHAIN_BROKEN` warning but does not abort.

### 5.3 CLI unit (`tests/eval/test_metrics.py`) — 12 cases

Pure-Python tests against synthetic histories (no server, no disk except a fixture tree built in-test).

1. Empty corpus → report with zeros and no per-run rows.
2. One run, one event → per-run + aggregate populated correctly.
3. Mixed reviewers → `summary.unique_reviewers` sorted (None last by convention).
4. `--reviewer takaki` filters out other reviewer's events.
5. `--include-clipped` toggle changes timing aggregates but not agreement.
6. Confusion matrix: 3 events flipping A→B, B→A, A→A → matrix entries `[A][B]=1, [B][A]=1, [A][A]=1`.
7. Round-trip cancellation: edit A→B then B→A → first phase event has `from_value=A`, segment final phase = A → matrix[A][A]+=1 only (no double-count).
8. `by_source` for an unedited segment with `label_source="vlm_with_object_state"` and matching auto = final → agreement++.
9. `by_confidence_bucket` boundary: confidence == 0.7 exactly → goes in `[0.7,1.0]` (right-closed top bucket).
10. Pre-D run warning: a run with `edited_at` set but `history=[]` → warning emitted, run excluded from `runs_with_history`.
11. Markdown rendering: render a deterministic report, snapshot-compare against checked-in fixture.
12. `--schema-version v3.0` (future) → `EVAL_SCHEMA_INCOMPATIBLE` per affected run.

### 5.4 Regression (cross-cutting)

- Existing B r1 PATCH unit tests (18 cases) still green — `apply_edit`'s new history append must not change observed PATCH response, ETag, or non-history annotation diff.
- Existing `mimicanno annotate` end-to-end test still green — the schema bump to v2.0 is loader-back-compatible.
- Frontend vitest 3 cases from B r1 (T14) still green; one new case: PATCH client sends `client_edit_duration_ms` when dropdown timing was captured (mock `performance.now`).

### 5.5 Smoke (manual)

`runs/so101_phase4_v5/` real episodes: re-run `mimicanno serve`, do 5 dropdown edits in the UI across 2 episodes, run `uv run mimicanno eval runs/`. Inspect:
- `human_edit_time.aggregate.client_coverage` ≥ 0.8 (most edits had a captured client duration).
- `label_agreement.by_source` non-empty.
- Markdown report renders cleanly (≤100 char lines, no broken tables).

---

## 6. Exit criteria

1. ✅ `EditEvent` schema lands in `mimicanno/schema.py` and `annotation.schema.json`; `schema_version` bumps to v2.0.
2. ✅ `apply_edit` appends one `EditEvent` per PATCH; atomicity preserved (server unit test #1 + integration #1).
3. ✅ `client_edit_duration_ms` round-trips from frontend → PATCH body → history (server unit #2).
4. ✅ Invalid client durations are silently dropped (server unit #3, #4).
5. ✅ Server-side `server_inter_event_ms` populated for every event; clipping flag honored (server unit #7).
6. ✅ Conditional emit: un-edited runs produce byte-identical `annotation.json` (server unit #10).
7. ✅ Hash chain `prev_run_hash` ↔ `new_run_hash` consistent across consecutive events (server unit #6).
8. ✅ `mimicanno eval` CLI exists and emits both JSON and Markdown matching §4.2 shape.
9. ✅ `human_edit_time.per_run` and `aggregate` computed per §4.3 semantics.
10. ✅ `label_agreement.confusion_matrix`, `by_source`, `by_confidence_bucket`, `by_phase` computed per §4.3.
11. ✅ Pre-D runs (edited_at present, history empty) generate a `PRE_D_RUN` warning and are excluded from timing aggregates.
12. ✅ All 27 new tests (12 server unit + 3 integration + 12 CLI) green. All existing PATCH-surface tests across the 5 B-r1 files (`test_edit_repo.py` 17, `test_routes_patch.py` 15, `test_routes_patch_cycle.py` 3, `test_patch_concurrent.py` 1, `test_edit_short_circuit.py` 2 = **38 cases total**) remain green without modification. Repo-wide test suite (1100+) green.
13. ✅ mypy --strict clean over `mimicanno/eval/` and changed lines in `mimicanno/server/edit_repo.py`.
14. ✅ Frontend dropdown captures focus→change duration and forwards it in PATCH body. Vitest case covers the new code path.
15. ✅ Manual smoke (§5.5) on `runs/so101_phase4_v5/` shows ≥0.8 client_coverage (over phase events) and a non-empty agreement table.
16. ✅ **(rev2)** `boundary_repo.patch_boundary` and `reviewed_repo.patch_reviewed` each append an `EditEvent` with the correct `field` value. Server unit tests #13–#16 green.
17. ✅ **(rev2)** Mixed-field PATCH chain produces 3 events with intact hash chain (server unit test #17).
18. ✅ **(rev2)** `mimicanno/server/history_event.py::build_event` exists as a pure function consumed by all 3 repos; covered by 1 unit test (#18).

---

## 7. Risks and open questions

- **Client clock skew across machines**: the editor and server may have different clocks. `client_edit_duration_ms` is a delta, not a wall time, so skew doesn't matter for that field. `server_inter_event_ms` uses server clock only. ✅
- **Multi-tab editing**: if a reviewer has two browser tabs open and edits the same segment in both, the two PATCHes race (B r1 §5.1 #13 covers this — exactly one wins). The loser 412s without writing history. ✅
- **Reviewer churn mid-edit**: `MIMICANNO_REVIEWER` env is read at server startup, so a single `mimicanno serve` invocation has one reviewer. Multi-reviewer collaboration requires multiple serve processes pointing at the same `runs/`, which already needs B r1's lock. Documented as expected.
- **History grows unbounded**: a chatty reviewer could append thousands of events per run. At ~300 bytes per event, 10k events = 3 MB of annotation.json. Still fine for JSON parsing, but the UI's annotation.json fetch may slow. Deferred: pagination or windowing in D r2 if it becomes a real problem.
- **`generated_at` as causal anchor**: the first edit's `server_inter_event_ms` measures from pipeline completion, which may be hours/days before the human looks at the run. Without clipping this **over-counts** (the metric absorbs the entire idle gap between annotate completion and reviewer arrival); the 1h clip caps that over-count at 3,600,000 ms. Net direction of bias: **upward** for any run where reviewer arrival > 1h after pipeline completion (most production runs). Documented in `mimicanno eval --help`. A cleaner anchor (frontend-supplied `client_session_started_ms`) was considered and deferred to D r2 — it adds a new PATCH body field and changes the contract; not worth the surface area for r1.
- **Concurrent eval during serve**: `mimicanno eval` reads `annotation.json` without taking the runs/index.json.lock. Possible to read a partially-written file mid-PATCH? **No** — annotation.json is written via tmp+os.replace (B r1 §3.5), so readers see either old or new bytes, never partial. ✅
- **`label_source` overwrite loses provenance**: PATCH sets `label_source = "human_edit"`, overwriting whatever it was. The first phase event's `from_value` recovers the pre-edit phase but **not** the pre-edit `label_source`. Eval treats the first event as the auto-source-of-record only when the segment was first edited from a non-human source; for segments edited from `human_edit` → `human_edit` (re-edit), we skip the "by_source" attribution and bucket under `unknown_pre_source`. Documented in §4.3 footnote.
- **B r2+ field expansion**: when B r2 (boundary drag) ships, EditEvents with `field="boundary"` start appearing. D r1's `human_edit_time` arithmetic is field-agnostic (just sums durations), so it works unchanged. `label_agreement` only filters to `field == "phase"` events. New metrics for boundary edits live in D r2.

---

## 8. Implementation order (informs the plan — rev2)

1. **Schema**: `EditEvent` dataclass, `AnnotationResult.history`, JSON schema bump, conditional emit, loader. Schema-version literal regression test BEFORE bump.
2. **Helper**: `mimicanno/server/history_event.py::build_event` (extracted from rev1's inline `_build_event`) + unit test (server unit #18).
3. **`edit_repo.apply_edit` extension** + server unit tests #1–#12.
4. **PATCH body validator extension** (phase endpoint only) + body schema (single-line addition to `routes.py`).
5. **(rev2) `boundary_repo.patch_boundary` extension** + server unit tests #13, #14.
6. **(rev2) `reviewed_repo.patch_reviewed` extension** + server unit tests #15, #16.
7. **(rev2) Mixed-field chain test** (#17) + integration test #1 updated to mix 3 fields.
8. `mimicanno/eval/` package: `metrics.py` (pure functions with `field=="phase"` filter for label_agreement), `render.py` (markdown with `client_coverage_by_field`), `cli.py` (arg parsing → orchestration).
9. CLI subcommand wiring in `mimicanno/cli.py`.
10. 12 CLI unit tests + 3 integration tests (TDD).
11. Frontend dropdown timing capture + vitest update.
12. mypy strict pass.
13. Manual smoke on `runs/so101_phase4_v5/` — exercise phase + boundary + reviewed PATCHes through the UI.
14. README extension (`mimicanno/server/README.md` + top-level `README.md` `## Eval` section).
15. notes `2026-05-16-phase5-d-eval-results.md` + memory update.
