# MimicAnno Phase 4 — Temporal smoothing design

Status: **draft**, awaiting review (Codex).
Author: brainstorming session 2026-04-29.
Supersedes: nothing — new sub-plan.
Parent spec: [`2026-04-25-mimicanno-design-brushup.md`](./2026-04-25-mimicanno-design-brushup.md) (§3 phase decomposition, §4.1 hashing, §6.4 confidence formula, §6.6 artifact schema versioning, §8.4 reserved labels, §10 Phase 4 outline, §11 error table, §12 package layout, §15.4 exit criterion #16).
Sibling: [`2026-04-28-mimicanno-phase3-sam3-tracking-design.md`](./2026-04-28-mimicanno-phase3-sam3-tracking-design.md) (Phase 3 — Phase 4 consumes the Phase 3 segment list shape; additive only).

## Reviewer context

(For reviewers unfamiliar with the parent spec — skim if you've already read it.)

### What is MimicAnno?

MimicAnno is a robot-episode subtask annotator: a CLI that ingests `(video, parquet, task_text)` and emits a per-segment subtask labeling under a versioned run directory `runs/<canonical_name>/{manifest, annotation, boundaries, signals[, tracks]}.json`. Phase 1 produces `phase="unlabeled"` skeleton segments from gripper / EEF / action signals; Phase 2 fills each segment with one of a fixed allowed-label set via Gemma; Phase 3 adds SAM3 object tracking + object-aware boundaries + object-aware relabeling.

### How the work is staged

```
Phase 1: signals-based boundary detection + read-only viewer        ← SHIPPED
Phase 2: provisional VLM labeling                                   ← SHIPPED
Phase 3: SAM3 + integrated boundary score + object-aware relabel    ← SHIPPED
Phase 4: temporal smoothing                                         ← THIS SPEC
Phase 5: human-edit UI + parquet export + evaluation
```

Each phase produces a **separate canonical run directory** (parent spec §4.1: `target_phase` ∈ `config_hash` → distinct `run_hash`). Phase N re-runs from the original episode inputs; it does **not** chain off Phase N-1's artifacts at runtime. Phase 4 is no exception: `mimicanno annotate --target-phase 4 ...` re-runs signals → boundaries → SAM3 → labeling → smoothing in one process.

### What Phase 4 (this spec) does

Phase 4 introduces **temporal smoothing** as a deterministic post-pass over the segment list emitted by Phase 3 (or Phase 2, in the Phase-3-objectless degrade case). Three operators run in fixed order:

1. **Same-label merge.** Adjacent segments with identical `phase` collapse into one.
2. **Min-duration absorb.** Segments shorter than `min_segment_duration_sec` get folded into their highest-`overall_confidence` neighbor (parent spec §10), then same-label merge runs again.
3. **Viterbi relabel** (default on, disable via `viterbi_enabled=false`). A constrained dynamic-programming pass over the segment sequence finds the labeling that maximizes `sum(emission) + sum(transition_penalty)`, where `transition_penalty[a,b] = -lambda_forbidden` for `(a,b) ∈ forbidden_transitions` and `0` otherwise. Same-label merge runs once more after Viterbi.

Schema is purely additive: a new per-segment `smoothing_ops: list[str]` field (default `[]` for Phase 1–3 runs) and a top-level `manifest.smoothing_summary` block (Phase 4 only). `label_source` enum is **unchanged** — Viterbi can flip a segment's `phase`, but the label's lineage (`vlm_with_object_state`, `vlm_robot_state_only`, `signals_only`) is preserved; `smoothing_ops` is the only place the smoothing operations are recorded.

If you're a reviewer evaluating this spec, the question is: **could a competent engineering team take this document and produce an implementation that (a) satisfies parent-spec exit criterion §15.4 #16, (b) does not violate the parent-spec invariants on hashing / atomicity / schema versioning / error idiom, (c) preserves Phase 1/2/3 behavior unchanged at the byte level (same `run_hash`, same artifacts), and (d) leaves Phase 5 work unobstructed?**

## 0. Scope and intent

In scope:

- New `mimicanno/smoother.py` (parent spec §12 layout). Public API surface: `SmootherConfig` dataclass, `Smoother` class, `apply_smoothing(segments, *, config) → SmoothingResult` function, `SmoothingResult` dataclass (`segments`, `summary`, `ops_log`).
- Three deterministic ops (§3) applied in fixed order.
- New `target_phase=4` orchestrator: `annotate_episode_phase4(req: AnnotateRequest) → AnnotateResult` in `pipeline.py`. Internally re-uses `annotate_episode_phase3` machinery up through the labeled-segments stage, then runs the smoother, then writes artifacts.
- `mimicanno annotate --target-phase 4 [--smoother-config <yaml>] [--no-viterbi] ...` CLI extension. Phase 1/2/3 invocations remain identical.
- New per-segment field `smoothing_ops: list[str]` (additive, default `[]`).
- New manifest block `smoothing_summary` (Phase 4 only; absent for Phase 1–3 manifests).
- Hash payload extension: `SmootherConfig.to_dict()` enters `config_hash` only when `target_phase >= 4`.
- Test strategy across 3 layers (unit per op / integration with FixtureVLM + FixtureSAM3 / Phase 1-3 no-regression).

Non-goals:

- **No HMM / Bayesian decoding.** Viterbi here is a constrained DP over a 1-segment-deep observation model; emissions are point estimates from the VLM, not distributions. A full HMM with per-frame observations is Phase 5+ territory if it ever comes up.
- **No frame-level smoothing.** Phase 4 operates on the segment list, not on the per-frame label sequence. Re-bracketing from frame-level scores is out of scope.
- **No new boundary detection.** Smoothing only re-arranges and re-labels segments produced by upstream stages; `boundaries.json` content for Phase 4 is identical to what Phase 3 (or Phase 2) would have produced for the same inputs and config.
- **No new artifact file.** Smoothing outputs are folded into `annotation.json` (per-segment) and `manifest.json` (summary). No `smoothing.json`.
- **No new `label_source` enum value.** Smoothing preserves lineage; `smoothing_ops` is the operations log.
- **No automatic `failure_flags` inference.** Forbidden transitions surface as "low overall_confidence" rather than auto-injecting flags. Failure inference stays Phase 5.
- **No viewer changes.** Phase 4 is invisible to the existing viewer except that segment count drops; no `smoothing_ops`-aware overlay. Phase 5 may add one.
- **No re-run of Phase 1/2/3 with smoothing applied retroactively.** Phase 4 is a separate `target_phase`; existing Phase 1/2/3 run dirs are untouched.

## 1. Architecture

### 1.1 Phase 4 in the pipeline

```
mimicanno annotate --target-phase 4 [--smoother-config <yaml>] ...
  │
  ├─ inputs validated (video, parquet, task_text, robot_adapter, labels)
  ├─ AnnotationConfig assembled (boundary + vlm + tracking + smoother sub-blocks)
  ├─ run_hash computed
  │     - target_phase=4 ∈ config_hash → distinct from any Phase 1/2/3 run_hash
  │     - SmootherConfig in config_hash (only when target_phase >= 4)
  │     - VLM + SAM3 + tracking config inherited from Phase 3
  │
  ├─ canonical_name resolved (parent spec §4.1)
  │
  ├─ [Phase 1+2+3 inline]   re-run the existing Phase 3 inner pipeline:
  │     signals → boundaries → SAM3 (or Phase-3-objectless degrade) → VLM labeling
  │     → labeled_segments: list[SubtaskSegment]  (same shape Phase 3 emits)
  │
  ├─ [Phase 4 new]   smoothing pass:
  │     SmoothingResult = apply_smoothing(labeled_segments, config=SmootherConfig)
  │     → smoothed_segments: list[SubtaskSegment]   (same dataclass; possibly fewer, possibly relabeled)
  │     → SmoothingSummary (counts + per-op outcomes)
  │
  ├─ stamp every smoothed segment:
  │     - smoothing_ops: list[str]  (e.g., ["merge_same_label"], ["merge_short", "viterbi_relabel"])
  │     - label_source: UNCHANGED (preserves lineage)
  │     - segment_id: regenerated to be deterministic on the smoothed sequence (§4.2)
  │     - boundary_confidence / overall_confidence: recomputed (§3.5)
  │
  └─ writers emit artifacts to runs/<canonical_name>/:
        - manifest.json        (with smoothing_summary block; pipeline_status.target_phase=4)
        - annotation.json      (smoothed segments, each with smoothing_ops field)
        - boundaries.json      (UNCHANGED from upstream — boundaries detected on raw signals)
        - signals.json         (UNCHANGED)
        - tracks.json          (when SAM3 succeeded — UNCHANGED)
```

The orchestrator is **not** a chain over a Phase 3 run dir on disk; it re-runs the inner Phase 3 work in-process. This preserves the parent spec's "each phase is a self-contained run" invariant and avoids the failure mode of "Phase 4 reads a stale Phase 3 artifact, smooths it, and produces an inconsistent `manifest.config_hash`."

### 1.2 Module layout (additions)

```
mimicanno/
  smoother.py                 # NEW. ~250 LOC target.
    SmootherConfig             - dataclass: defaults + .to_dict() for hashing
    SmoothingOp                - Literal["merge_same_label", "merge_short", "viterbi_relabel"]
    SmoothingSummary           - dataclass: per-op counts + initial / final segment counts
    SmoothingResult            - dataclass: segments + summary + ops_log[(op, segment_ids_affected)]
    apply_smoothing()          - top-level callable; calls 3 ops in order
    _merge_same_label()        - internal step
    _merge_short()             - internal step
    _viterbi_relabel()         - internal step
  pipeline.py                  # add annotate_episode_phase4 orchestrator (~80 LOC)
  cli.py                       # add --smoother-config + --no-viterbi flags (~30 LOC)
  config.py                    # add SmootherConfig + load_smoother_config_yaml + AnnotationConfig.smoother field
  schema.py                    # add SubtaskSegment.smoothing_ops + Manifest.smoothing_summary
  schema_versions.py           # bump annotation 0.1.0 → 0.2.0 (additive minor; reader-tolerant)
  errors.py                    # add Phase 4 error codes (§7)
tests/unit/
  test_smoother_merge_same_label.py
  test_smoother_merge_short.py
  test_smoother_viterbi.py
  test_smoother_apply.py
  test_smoother_config.py
tests/integration/
  test_phase4_happy_path.py
  test_phase4_no_phase123_regression.py
  test_phase4_viterbi_disabled.py
  test_phase4_smoother_yaml_override.py
```

## 2. SmootherConfig

```python
# mimicanno/config.py

@dataclass(frozen=True)
class SmootherConfig:
    """Phase 4 smoother parameters.

    Defaults match parent spec §10. Hash payload (``to_dict``) is included in
    ``config_hash`` only when ``target_phase >= 4``; for Phase 1–3 runs the
    field stays ``None`` and contributes nothing.
    """

    min_segment_duration_sec: float = 0.30
    merge_threshold_sec: float = 0.20      # currently unused; reserved for future
                                           # short-segment merge variants. Hashed
                                           # so future work doesn't produce a
                                           # silent config_hash drift.
    forbidden_transitions: tuple[tuple[str, str], ...] = (
        ("grasp_object",   "approach_object"),
        ("release_object", "grasp_object"),
        ("lift_object",    "idle"),
    )
    viterbi_enabled: bool = True
    lambda_forbidden: float = 0.5          # transition penalty magnitude (§3.4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_segment_duration_sec": self.min_segment_duration_sec,
            "merge_threshold_sec": self.merge_threshold_sec,
            "forbidden_transitions": [list(p) for p in self.forbidden_transitions],
            "viterbi_enabled": self.viterbi_enabled,
            "lambda_forbidden": self.lambda_forbidden,
        }


@dataclass(frozen=True)
class AnnotationConfig:
    target_phase: int
    model_config: ModelConfig
    boundary: BoundaryConfig
    vlm: VLMConfig | None = None
    tracking: TrackingConfig | None = None
    smoother: SmootherConfig | None = None  # NEW. Required iff target_phase >= 4.

    def to_dict(self) -> dict[str, Any]:
        d = {
            "boundary": self.boundary.to_dict(target_phase=self.target_phase),
            "target_phase": self.target_phase,
            "model_config": self.model_config.to_dict(),
        }
        if self.target_phase >= 2 and self.vlm is not None:
            d["vlm"] = self.vlm.to_dict()
        if self.target_phase >= 3 and self.tracking is not None:
            d["tracking"] = self.tracking.to_dict()
        if self.target_phase >= 4 and self.smoother is not None:
            d["smoother"] = self.smoother.to_dict()
        return d
```

### 2.1 YAML override

`--smoother-config <path.yaml>` populates `SmootherConfig` analogously to Phase 1's `--boundary-config` (parent spec §4.5). All fields overridable; missing fields fall back to defaults. `--no-viterbi` is a CLI sugar that overrides `viterbi_enabled=false` and wins over the YAML.

YAML schema:

```yaml
min_segment_duration_sec: 0.30
merge_threshold_sec: 0.20
forbidden_transitions:
  - [grasp_object, approach_object]
  - [release_object, grasp_object]
  - [lift_object, idle]
viterbi_enabled: true
lambda_forbidden: 0.5
```

`load_smoother_config_yaml(path: Path) → SmootherConfig` lives in `mimicanno/config.py`. Validation: `lambda_forbidden >= 0`, `min_segment_duration_sec >= 0`, `merge_threshold_sec >= 0`, every forbidden-transition tuple has length 2 and references known allowed labels OR a reserved label (`unlabeled`/`unknown`). Validation errors raise `ConfigError` with `error_code="smoother_config_invalid"` (§7).

## 3. Algorithm

### 3.1 Inputs and invariants

`apply_smoothing(segments, *, config)` consumes `list[SubtaskSegment]` (the labeled list emitted by `apply_phase2_labeling` or `apply_phase3_labeling`) and returns a new list. Pre-conditions:

- `segments` is sorted by `start_frame` ascending and non-overlapping.
- Every segment has a finite `vlm_confidence ∈ [0, 1]` OR `vlm_confidence is None` (Phase 1 reserved-phase case — but Phase 1 segments don't reach Phase 4 because Phase 4 inherits Phase 3's labeling).
- `boundary_confidence ∈ [0, 1]`, `overall_confidence ∈ [0, 1]`.

Empty input (`segments == []`) returns an empty result with all op counts `0` and no error. Single-segment input returns the input unchanged with all op counts `0` (no merge possible, no Viterbi transition).

### 3.2 Op 1 — same-label merge

For each adjacent pair `(s_i, s_{i+1})` with `s_i.phase == s_{i+1}.phase`, replace them with a merged segment. Repeat until no adjacent pair shares a phase. Iteration is left-to-right, single-pass per round; the loop terminates when no merge happens in a round.

Merged-segment fields:

| Field | Rule |
|---|---|
| `start_frame`, `start_time` | from `s_i` |
| `end_frame`, `end_time` | from `s_{i+1}` |
| `phase`, `verb`, `object`, `target` | from the higher-`overall_confidence` segment; ties → `s_i` |
| `failure_flags` | sorted set-union of both lists |
| `label_source` | from the higher-`overall_confidence` segment; ties → `s_i` (lineage preserved per §0) |
| `object_state_unavailable` | `s_i.object_state_unavailable OR s_{i+1}.object_state_unavailable` |
| `object_track_ids` | sorted set-union |
| `label_version` | identical across the run; if they differ, that's a bug — assert |
| `start_boundary` | from `s_i` (the original outer-left boundary) |
| `end_boundary` | from `s_{i+1}` (the original outer-right boundary) |
| `boundary_confidence` | `max(s_i.boundary_confidence, s_{i+1}.boundary_confidence)` |
| `vlm_confidence` | duration-weighted mean of the two; `None` only if both are `None` |
| `overall_confidence` | recomputed via parent spec §6.4 from the merged `boundary_confidence` + `vlm_confidence` (so this stays a derived value, not a max-of-merged) |
| `evidence` | from the higher-`overall_confidence` segment (string); ties → `s_i` |
| `reviewed`, `reviewer_id` | both reset to `False` / `None` (smoothing invalidates any prior review state) |
| `smoothing_ops` | `s_i.smoothing_ops + ["merge_same_label"]` (deduped on consecutive identical entries) |
| `segment_id` | regenerated (§4.2) |

### 3.3 Op 2 — min-duration absorb

Iterate left-to-right. For each segment with `(end_time - start_time) < min_segment_duration_sec`:

1. Identify candidate neighbors: left (`s_{i-1}`) if `i > 0`, right (`s_{i+1}`) if `i < len-1`.
2. Score each candidate as its `overall_confidence`.
3. Pick the higher-scoring neighbor. If equal, prefer the neighbor that does **not** induce a forbidden transition with the segment on the *opposite* side after the absorb (rare tie-breaker; if both are equally good or equally bad, prefer left).
4. Merge the short segment into the chosen neighbor using the same field-merge rules as Op 1, except `phase` (and `verb`/`object`/`target`) is taken from the neighbor (not from the higher-confidence side — neighbor wins because absorb preserves the dominant label of the surviving segment).
5. The absorbed segment's `smoothing_ops` is appended to the neighbor's `smoothing_ops` with `"merge_short"` added (deduped).
6. After all short segments are absorbed in one left-to-right pass, run Op 1 again (merge_same_label) to collapse any newly adjacent same-phase pairs.

Edge case: a single-segment input with duration `< min_segment_duration_sec`. No neighbors → the segment survives untouched. (This is the "tiny episode" case; we don't fail.)

Edge case: all segments are below threshold. The loop absorbs them pairwise; the final result is one long segment (or as few as possible).

### 3.4 Op 3 — Viterbi relabel

If `config.viterbi_enabled is False`, skip. Otherwise:

- States `Q` = the set of allowed labels for this run (from `labels.yaml`) ∪ `{"unknown"}` (reserved). `"unlabeled"` is excluded — only Phase 1 ever emits it, and Phase 4 runs on Phase 2/3 labeled segments.
- Observations: the segment list `[s_1, ..., s_T]`. The "observation" of segment `s_t` is `(observed_phase_t, vlm_confidence_t)`.
- Emission score `e(s_t, q) = vlm_confidence_t` if `q == observed_phase_t`, else `0.0`. Segments with `vlm_confidence_t is None` use `e(s_t, q) = 0.0` for all `q` (Viterbi will pick whatever transition score wins). Segments with `phase == "unknown"` and `vlm_confidence_t = 0.0` thus contribute zero emission and will be dictated by transitions.
- Transition score `tr(q_a, q_b) = -lambda_forbidden` if `(q_a, q_b) ∈ forbidden_transitions`, else `0.0`.
- Decoding: standard Viterbi on the segment-sequence DAG. Find `argmax_{q_1...q_T} sum_t e(s_t, q_t) + sum_t tr(q_t, q_{t+1})`.
- For each segment `s_t` whose decoded `q*_t != s_t.phase`, replace `s_t.phase`, `verb`, `object`, `target` with the decoded label's canonical entry (looked up via labelset; `verb`/`object`/`target` come from the labelset YAML, not from the original VLM output). Append `"viterbi_relabel"` to `smoothing_ops`. Recompute `overall_confidence` per parent spec §6.4. `evidence` keeps the original VLM evidence (transparency: "VLM said X, smoother flipped to Y because X→next was forbidden").
- After Viterbi, run Op 1 (merge_same_label) once more to collapse any newly adjacent same-phase pairs created by the relabel.

Tie-breaking in Viterbi: when two paths have equal score, prefer the path that keeps the most segments at their observed label (i.e., minimizes total relabels). Implementation: include a small ε secondary score equal to `1e-6 * count(q_t == observed_phase_t)` per path; this keeps stability without affecting decisions.

### 3.5 Confidence recomputation

Whenever a segment is merged or relabeled, `overall_confidence` is recomputed from scratch using the parent spec §6.4 formula. The parent spec defines:

```
overall_confidence(seg) = 0.0  if seg.phase ∈ {"unlabeled", "unknown"}
                        = mean(boundary_confidence, vlm_confidence)  otherwise
                        (with vlm_confidence treated as 0 if None)
```

The smoother does NOT introduce a new "smoothing_confidence" sub-component (parent spec §16 explicitly defers that — "add only when needed"). The smoothed segment's `overall_confidence` reflects the merged boundary and VLM signals only.

### 3.6 Per-segment boundary integrity

After all ops, for each surviving segment:

- `start_boundary` and `end_boundary` reference the original boundary candidates (by frame). Internal boundaries that were absorbed into a merged segment are dropped from the segment-level view but **remain** in `boundaries.json` (which is unchanged by smoothing).
- The `BoundaryRef.frame` of `start_boundary[s_i+1]` always equals the `BoundaryRef.frame` of `end_boundary[s_i]` for adjacent `s_i, s_{i+1}` (no gaps, no overlaps). This invariant is asserted post-smoothing.

## 4. Schema additions

### 4.1 `SubtaskSegment.smoothing_ops`

```python
@dataclass(slots=True)
class SubtaskSegment:
    ...                                  # existing 18 fields unchanged
    smoothing_ops: list[str]             # NEW. default-empty for Phase 1–3 runs.
```

`smoothing_ops` is a chronological log of operator names applied to this segment as it emerged from the smoother. Allowed string values:

- `"merge_same_label"` — this segment is a merge result (or downstream descendant) of an Op 1 step.
- `"merge_short"` — this segment absorbed a sub-`min_segment_duration_sec` neighbor in Op 2.
- `"viterbi_relabel"` — Viterbi changed this segment's `phase` from the VLM's choice.

Order matters: `["merge_same_label", "viterbi_relabel"]` means a merge happened first, then Viterbi flipped the merged segment's label. Consecutive duplicates collapse: if two `"merge_same_label"` rounds touch the same segment, only one entry is recorded.

For Phase 1/2/3 runs, every segment has `smoothing_ops == []`. The field is written to `annotation.json` always (no version-conditional emission), so old readers see it as an unknown-but-empty list. The to_dict / from_dict roundtrip pins the empty default to `[]`, never `null`.

Validation (`__post_init__`):

```python
if self.smoothing_ops is None:
    raise TypeError("smoothing_ops must be list[str], not None")
ALLOWED_OPS = {"merge_same_label", "merge_short", "viterbi_relabel"}
for op in self.smoothing_ops:
    if op not in ALLOWED_OPS:
        raise ValueError(f"unknown smoothing op: {op!r}")
```

### 4.2 `segment_id` regeneration

`segment_id` is currently derived in Phase 1 bracketing as `f"{episode_id}__seg{idx:04d}"` where `idx` is the 0-based index in the bracketed list. After smoothing, the segment count and ordering change, so segment IDs must be regenerated. Phase 4 sets:

```python
seg.segment_id = f"{episode_id}__seg{idx:04d}__sm"
```

The `__sm` suffix marks the segment as smoothed and prevents accidental ID collisions if a Phase 3 and a Phase 4 run dir end up adjacent in some downstream consumer's view. (They live under different `canonical_name`s, so this is belt-and-suspenders.)

### 4.3 `Manifest.smoothing_summary`

```python
@dataclass(slots=True)
class SmoothingSummary:
    initial_segment_count: int
    final_segment_count: int
    merge_same_label_rounds: int       # how many full sweeps it took to converge in Op 1
    merge_same_label_collapses: int    # total adjacent-pair collapses across all rounds
    merge_short_absorbs: int           # how many short segments got absorbed in Op 2
    viterbi_relabels: int              # how many segments Viterbi flipped (0 if disabled)
    viterbi_skipped: bool              # True when viterbi_enabled=False or T <= 1
```

`Manifest.smoothing_summary: SmoothingSummary | None`. `None` for Phase 1–3 manifests; populated for Phase 4. Schema_version stays 0.1.0 for manifest because the addition is a new optional top-level key (parent spec §6.6 allows additive minor changes within the same major).

### 4.4 `annotation.json` schema_version bump

Adding `smoothing_ops` to every segment is additive but per-row (not optional top-level), so we bump `annotation` from `0.1.0` to `0.2.0`. Parent spec §6.6 reads:

> COMPAT scope: in-run artifacts only. Consumers verify producer-declared majors against `supported_majors` set membership (NOT `>=`).

So a 0 → 0 stays unchanged; the MINOR bump is a producer-side note for forward consumers. Reader code must accept both `0.1.0` (for re-reading old Phase 1–3 runs) and `0.2.0` (for Phase 4 runs). The reader treats a missing `smoothing_ops` field as `[]`.

Concretely:

```python
# schema_versions.py
ARTIFACT_SCHEMA_VERSIONS: dict[str, str] = {
    "manifest": "0.1.0",
    "annotation": "0.2.0",   # was 0.1.0
    "boundaries": "0.1.0",
    "signals": "0.1.0",
}

# COMPAT_BLOCK still parses majors → unchanged. 0.2.0 → MAJOR=0.
```

`from_dict` for `SubtaskSegment` accepts both versions; the `Annotation` artifact carries the producer-declared version (0.1.0 for Phase 1–3 runs, 0.2.0 for Phase 4). Tests cover both load paths.

## 5. CLI

```
mimicanno annotate \
  --video ... --parquet ... --task ... --robot ... \
  --target-phase 4 \
  --vlm-model google/gemma-4-E2B-it \
  --sam3-checkpoint /path/to/sam3.ckpt \
  --smoother-config configs/smoother/default.yaml \   # optional
  [--no-viterbi]                                       # optional sugar
```

Flag handling:

- `--smoother-config <path>`: parsed via `load_smoother_config_yaml`. Errors raise `error_code="smoother_config_invalid"` and exit 2.
- `--no-viterbi`: sets `SmootherConfig.viterbi_enabled = False`, overriding the YAML if both are present.
- `--target-phase` validation extends to accept `4`. Phase 4 requires the same Phase 3 inputs (`--vlm-model`, `--sam3-checkpoint`) — pre-flight (parent spec §2.5) reuses Phase 3's checks.

Pre-flight order for `target_phase=4`:

1. All Phase 3 pre-flight (vlm_checkpoint_resolved, sam3_checkpoint_resolved, …).
2. NEW: smoother_config validation (if `--smoother-config` given). Catches YAML schema errors before the run starts.

Default `configs/smoother/default.yaml` is shipped (mirrors `SmootherConfig` defaults verbatim) so users can edit a copy.

## 6. Hashing

Per parent spec §4.1:

```
config_hash = sha256(json_canonical(AnnotationConfig.to_dict()))
run_hash    = sha256(config_hash || input_hash)
```

`AnnotationConfig.to_dict()` includes `smoother` only when `target_phase >= 4` (§2). This means:

- A Phase 1/2/3 run with otherwise-identical inputs produces a `config_hash` that is **byte-identical** to what the same code produced before Phase 4 was implemented. (Verified by `tests/integration/test_phase4_no_phase123_regression.py`, which pins hashes for the synth fixture.)
- A Phase 4 run with default `SmootherConfig` produces a different `config_hash` from a Phase 4 run with non-default `SmootherConfig`, even on the same inputs. This is the desired "hash-isolated" behavior so the `runs/` index can host both.
- A Phase 4 run with `viterbi_enabled=False` and a Phase 4 run with `viterbi_enabled=True` produce different `config_hash` (different `SmootherConfig.to_dict()`).

The `model_config` block does not change for Phase 4 — smoothing introduces no new model. `target_phase=4` enters `model_config` only via the `target_phase` top-level field; `vlm_model` / `sam3_model` / `sam3_checkpoint` come from the inherited Phase 3 settings.

## 7. Error handling and degrade

### 7.1 Phase 4-only error codes

| `error_code` | Detection | Action |
|---|---|---|
| `smoother_config_invalid` | YAML parse fails OR validation fails (§2.1) | Abort at pre-flight, exit 2, before any compute |
| `smoother_unknown_label_in_forbidden` | YAML forbidden_transitions reference a label not in the run's labelset and not reserved | Abort at pre-flight (subset of `smoother_config_invalid` — separate code for clarity) |
| `smoother_segment_invariant_violation` | Post-smoothing assertion fails (e.g., gap or overlap between adjacent segments, or `overall_confidence` recomputation produces NaN) | Abort with the failing assertion's frame range; this is a programming bug, not a user error |

### 7.2 No Phase 4 degrade path

Smoothing is deterministic and operates only on already-validated segments. There is no "smoothing failed; fall back to Phase 3 raw" mode. If Phase 3 itself degrades to Phase-3-objectless (parent spec §9.4 / Phase 3 spec §7.2), Phase 4 still smooths the resulting Phase-2-style labeled segments — the smoother is label_source-agnostic. The manifest's `pipeline_status.degraded_from_phase` field already records the Phase 3 degrade; smoothing adds nothing new to surface.

### 7.3 Smoothing-applied-to-empty / single-segment

Edge cases are handled silently:

- 0 segments in → 0 segments out, `SmoothingSummary` with all counts `0` and `viterbi_skipped=True`.
- 1 segment in → 1 segment out, `smoothing_ops=[]`, `viterbi_skipped=True` (Viterbi requires `T >= 2` for transitions to matter; a 1-segment Viterbi can only trivially keep the observed label, so we skip it for clarity in the summary).

## 8. Test strategy

### 8.1 Unit (`tests/unit/`)

Each op tested in isolation with hand-crafted segment fixtures:

- `test_smoother_merge_same_label.py` (~12 tests): adjacent same-phase pairs collapse; non-adjacent same-phase don't; multiple rounds converge; field-merge rules (max boundary_confidence, weighted-mean vlm_confidence, set-union of failure_flags, etc.); reset of `reviewed`/`reviewer_id`; segment_id regeneration with `__sm` suffix; empty input; single-segment input.
- `test_smoother_merge_short.py` (~10 tests): below-threshold absorbed into higher-confidence neighbor; ties broken by left-preference; no-neighbor case (single short segment passes through); all-short cascade collapse; absorb that creates a new same-label adjacency triggers Op 1 follow-up.
- `test_smoother_viterbi.py` (~12 tests): no-forbidden case = identity (every segment keeps its observed label); single forbidden pair flips the lower-confidence side; high-confidence segment in forbidden pair stays put (because flipping it costs more emission than gaining transition); `viterbi_enabled=False` skips entirely; `lambda_forbidden=0` skips effectively; `phase == "unknown"` segments get filled by transitions; Viterbi-then-merge produces correct same-label collapse.
- `test_smoother_apply.py` (~6 tests): full apply_smoothing pipeline on representative inputs; SmoothingSummary counts match reality; ops_log reflects what actually happened; idempotence (apply twice = apply once for stable inputs); deterministic output for identical input + config.
- `test_smoother_config.py` (~8 tests): YAML loader happy path; missing fields fall back to defaults; type errors raise `ConfigError`; unknown-label-in-forbidden raises `smoother_unknown_label_in_forbidden`; CLI `--no-viterbi` overrides YAML; round-trip (config → YAML → config = identity).

### 8.2 Integration (`tests/integration/`)

- `test_phase4_happy_path.py`: full `mimicanno annotate --target-phase 4` against the synth_aloha fixture with FixtureVLM + FixtureSAM3 (parent spec §11 #1 pattern). Asserts `manifest.pipeline_status.target_phase=4`, smoothing_summary present, segment count is `<=` Phase 3's segment count for the same fixture, every segment has `smoothing_ops` field (possibly empty), no forbidden transition with `overall_confidence > 0.5`.
- `test_phase4_no_phase123_regression.py`: pin `config_hash` and `run_hash` for `target_phase=1`, `target_phase=2`, `target_phase=3` runs against the synth fixture. Phase 4 code must NOT alter these hashes. Mirrors the Phase 3 hash-gating test (which exists at `tests/integration/test_phase3_no_phase12_regression.py`).
- `test_phase4_viterbi_disabled.py`: `--no-viterbi` produces a different `config_hash` and a smoothing_summary with `viterbi_skipped=true`, `viterbi_relabels=0`. Output may differ from default Phase 4 run by the relabels Viterbi would have made.
- `test_phase4_smoother_yaml_override.py`: `--smoother-config` with a non-default `lambda_forbidden=2.0` produces a different `config_hash` and a different relabel pattern than the default-config run on the same fixture.
- `test_phase4_per_segment_fallback.py`: Phase-3-objectless degrade still smooths the Phase 2-style labeled segments; smoothing_summary present; no Phase 4-specific error.

### 8.3 Gated real-data smoke

No new gated test in Phase 4 — smoothing has no model dependency. The Phase 3 real-SAM3 smoke test (`tests/test_phase3_real_sam3_smoke.py`) is unchanged.

### 8.4 Cross-artifact integrity (regression of parent spec §11 #6)

`test_phase4_cross_artifact.py` (extends the Phase 3 cross-artifact test): every `BoundaryRef` in a smoothed segment's `start_boundary` / `end_boundary` resolves to a candidate in `boundaries.json`. Internal boundaries lost to merge are still present in `boundaries.json` (they don't disappear from the boundaries artifact, only from the segment-level view).

## 9. Performance

Per parent spec §13 perf table:

| Component | Strategy | Budget |
|---|---|---|
| Smoother (Phase 4) | pure python, in-memory | < 0.1 s for 100 segments |

Smoothing is dominated by Op 3 Viterbi: O(T · |Q|²) where T = segment count, |Q| = label count. With T ~ 50 and |Q| ~ 10, that's ~5 000 ops per Viterbi run. Not a hot path.

## 10. Exit criteria

Per parent spec §15.4 #16:

> Smoothing reduces the segment count vs Phase 3 raw output and never produces a forbidden transition with high `overall_confidence`.

Concretely, Phase 4 ships when:

1. `mimicanno annotate --target-phase 4 ...` end-to-end produces a run dir with `pipeline_status.target_phase=4` and a non-null `smoothing_summary`.
2. On the synth_aloha fixture, Phase 4 default-config segment count `<=` Phase 3 default-config segment count for the same inputs.
3. No segment in any Phase 4 fixture run has `phase`-pair `(s_i.phase, s_{i+1}.phase) ∈ forbidden_transitions` AND `min(s_i.overall_confidence, s_{i+1}.overall_confidence) > 0.5` simultaneously.
4. Phase 1/2/3 `config_hash` and `run_hash` are byte-identical with vs without Phase 4 code present (regression test passes).
5. Annotation reader accepts both `schema_version=0.1.0` and `schema_version=0.2.0`.
6. Lint (ruff) clean, types (mypy --strict) clean, all unit + integration tests pass.

## 11. Open items / deferred

- **No frame-level confidence**: parent spec §16 defers per-frame label confidence; smoothing operates on segments only. If Phase 5 introduces per-frame correction, the smoother may need a re-design.
- **`merge_threshold_sec` is currently unused.** It exists in `SmootherConfig` because parent spec §10 names it. The current spec only has `min_segment_duration_sec` (Op 2). Future work may add a separate "merge segments shorter than `merge_threshold_sec` even if their labels differ" pass; until then, the field is hashed (so future addition doesn't change `config_hash` for already-shipped Phase 4 runs) but not consumed. Plan-reviewer should flag if this asymmetry feels wrong; alternative is to drop the field now and add it back with a `lambda_forbidden`-style explicit minor bump if/when the new pass lands.
- **No multi-step Viterbi window** (e.g., look-ahead beyond 1 transition). 1-step is sufficient for the forbidden-transition objective; longer windows are HMM territory.
- **No `failure_flags` auto-inference from Viterbi flips.** A flipped segment is an indicator that something doesn't fit, but auto-flagging `"failed_grasp"` from a Viterbi disagreement is a bridge too far without ground-truth validation. Phase 5 may add this with a human-in-the-loop check.

## 12. Questions for the user (gated by spec review)

1. **`merge_threshold_sec`**: keep as a hashed-but-unused field for now, or drop it from `SmootherConfig` until a real second-pass merge feature lands? (Open item §11.)
2. **`label_source` enum**: confirm we do NOT add `"smoothed_*"` values. Lineage-via-`smoothing_ops` is the proposal.
3. **`segment_id` `__sm` suffix**: confirm this is desirable, or should Phase 4 segment IDs reuse the Phase 3 form `seg0001` (counting on `canonical_name` to disambiguate at the run-dir level)?
4. **Default `lambda_forbidden=0.5`**: confirm. The intent is "a confidently-labeled VLM segment (vlm_confidence ≥ 0.5) is not flippable just to satisfy a forbidden transition." Higher values make Viterbi more aggressive.
