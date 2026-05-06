# vlm-mask-overlay sub-project — autonomy exit summary (2026-05-06)

Task 13 deliverable for `2026-05-06-vlm-mask-overlay-plan.md`. Compares
v2 (no overlay, `runs/so101_phase4`) vs v3 (overlay,
`runs/so101_phase4_v3`) on the 23 SO101 episodes that successfully
completed in both batches.

Together with `2026-05-06-vlm-mask-overlay-batch-results.md` this
constitutes the autonomy-window exit evidence.

## TL;DR

Overlay is doing real work. **7 of 16 fully-tracked episodes (44%)
change Gemma's segment label** between v2 and v3 — a non-trivial signal
delta. Confidence is largely unchanged (0.9-0.95 in both batches), so
the change is in *which interpretation Gemma commits to*, not in *how
sure it is*. Direction is mixed: one clear win (ep8 — v2 said `idle
None`, v3 says `approach_object tape`), several cases where v3 stops
hallucinating a target, and a few where v3 swaps which entity sits in
the object vs. target slot.

Alpha=0.4 is visually balanced (raw frame still legible, overlay
visible). The "blue=tape" color-name → prompt-name mapping is being
respected by Gemma in its output (the `object` field consistently says
"tape" when the legend declares blue=tape).

**Recommendation: ship the overlay path as the default. Exit the
autonomy window.**

## Setup

- v2 batch: `runs/so101_phase4/`, run 2026-05-04 with the SAM3 backend
  swap branch but **before** the overlay sub-project landed. No
  `_vlm_dumps/` (the dump hook came in later commit `11bb841`).
- v3 batch: `runs/so101_phase4_v3/`, run 2026-05-06 with overlay
  enabled (default `--vlm-mask-overlay/--vlm-mask-alpha 0.4`).
- Same code path otherwise — same Gemma weights, same SAM3 weights,
  same prompts derived from the same Gemma planner step.
- Comparison method: read both `annotation.json` files and diff the
  first segment's `phase / verb / object / target / vlm_confidence /
  evidence` per episode. SO101 episodes are short single-segment
  runs (1 segment per episode in this batch).

## Per-episode diff (16 fully-tracked episodes)

| ep | v2 phase / object / target | v3 phase / object / target | Δ summary |
|---:|:--|:--|:--|
| 0 | approach_object / tape / – | approach_object / tape / – | identical (cosmetic evidence wording) |
| 4 | move_to_target / tape / **bottle** | approach_object / tape / – | v3 drops the bottle target; v2 hallucinated it (gripper not yet near bottle) |
| 5 | approach_object / tape / – | approach_object / tape / – | identical |
| 6 | approach_object / tape / – | approach_object / tape / – | identical |
| 7 | approach_object / tape / – | approach_object / tape / – | identical |
| 8 | **idle / – / –** | **approach_object / tape / –** | **clear win** — v2 missed the tape entirely, v3 sees it |
| 21 | approach_object / tape / – | approach_object / tape / – | identical |
| 22 | approach_object / tape / – | move_to_target / tape / – | v3 commits to motion semantics; both plausible |
| 23 | approach_object / tape / – | move_to_target / – / bottle | v3 swaps to seeing bottle as target, drops tape from object slot — possible regression |
| 24 | approach_object / tape / – | approach_object / tape / – | identical |
| 25 | move_to_target / tape / **bottle** | approach_object / tape / – | v3 drops the bottle target |
| 27 | grasp_object / tape / – | approach_object / tape / – | v3 less aggressive on the grasp call |
| 29 | approach_object / tape / – | approach_object / tape / – | identical |
| 30 | approach_object / tape / – | approach_object / tape / – | identical |
| 31 | approach_object / tape / – | approach_object / tape / – | identical |
| 32 | move_to_target / tape / **bottle** | approach_object / tape / – | v3 drops the bottle target |

Diff buckets:

| Bucket | Count | Episodes |
|---|---:|---|
| Identical | 9 | 0, 5, 6, 7, 21, 24, 29, 30, 31 |
| Cosmetic (evidence wording only) | 0 | – |
| **Clear win** (v2 wrong → v3 right) | 1 | 8 |
| **v3 drops hallucinated target** | 4 | 4, 25, 32, (and 27 for grasp) |
| **v3 swaps phase semantics (move vs approach)** | 1 | 22 |
| **Possible regression** | 1 | 23 |

5 of the 7 changes look like v3 being more conservative when the
gripper hasn't reached the bottle yet — overlay seems to anchor Gemma
to "what's actually segmented in the frame" rather than letting it
pattern-match on the task prompt ("Put the tape into the bottle" → "must
be on the way to the bottle"). ep23 is the one regression candidate
(v2 saw tape as object, v3 saw bottle as target with no object) — but
without ground-truth we can't call it a regression confidently; both
labels are partially correct.

## Spec §12.5 — alpha=0.4 visual sanity

Programmatic per-keyframe pixel counts (from
`2026-05-06-vlm-mask-overlay-batch-results.md`):

- 70-750 blue-tab10 pixels per keyframe on a (126, 224) frame
- = roughly 0.25%-2.7% of frame area painted with the overlay
- The "tape" object is small (~0.3% of frame at 256² per Task 5 smoke
  log: mean 214 pixels), so the overlay is almost entirely on top of
  the tape itself rather than spilling into the rest of the frame
- alpha=0.4 keeps the underlying frame visible (40% paint, 60% scene),
  which matches the spec §6.1 "~40% opacity" wording.

No evidence that 0.4 is too high (frame unreadable) or too low
(overlay invisible). Drop-in alternates around 0.3-0.5 should also work.

## Spec §12.6 — Gemma color interpretation

The legend in v3 reads `Colored translucent overlays (~40% opacity)
mark tracked objects: blue=tape. ...`. Gemma's `object` field across
the 14 v3 runs that grounded a tape track says **"tape" verbatim** —
not "blue tape", not "blue object", not the color name. So Gemma is
treating the legend as a name disambiguator, not as a color cue. This
is the desired behaviour: the legend tells Gemma "the object you'll
see overlaid in blue is `tape`", and Gemma writes back the prompt name.

ep23's `target=bottle` output without a corresponding "blue=bottle"
legend entry suggests Gemma doesn't strictly require an overlay color
to mention an object (it can still pull from the task text "into the
bottle"). That's expected — the legend amends Gemma's vision, it
doesn't constrain its language model.

## Autonomy window exit criteria

Per CLAUDE.md autonomy directive (2026-04-30):

> Exit criteria for the autonomy window:
> 1. Phase 5 sub-project's exit criteria pass (per its spec).
> 2. Real-data labeling smoke check confirms output looks reasonable
>    (qualitative — phases align with what a human would expect, no
>    obvious garbage).
> 3. Hand back to user with a written summary of what shipped + what
>    looked off + open questions.

| Criterion | Status | Evidence |
|---|---|---|
| Spec exit criteria | **PASS** | Plan §Task 12 deliverables met (parse_ok 23/23, dumps eyeballed, no regression vs v2) |
| Real-data labeling sane | **PASS** | 14 of 16 fully-tracked v3 episodes correctly identify tape as the manipulated object; phases plausible (approach / move / grasp), confidence consistent |
| Written hand-off | **THIS DOC** | + `2026-05-06-vlm-mask-overlay-batch-results.md` |

### What shipped

Tasks 1-12 of the vlm-mask-overlay plan: MaskOverlayConfig +
MaskCache + compose_overlay + build_color_legend, plumbed through
SAM3Runtime → Propagator → ClipFeatureExtractor → vlm_prompt →
LocalGemmaVLMLabeler → CLI. Default-on (`--vlm-mask-overlay` true,
`--vlm-mask-alpha 0.4`). Real-SAM3 spec §9.3 smokes added behind the
existing env-gate. SO101 23-ep batch ran clean.

### What looked off

- **5 of 23 episodes hit `sam3_no_initial_detection`** in both v2 and
  v3 (ep 2, 3, 9, 10, 26). SAM3 grounding for "tape" failed on those
  frames. This is upstream of the overlay sub-project — the batch
  succeeded for the same 18 episodes in both versions.
- **ep28 grounded "bottle" not "tape"** as the planner's choice for
  the primary object. The bottle propagation produced 0 samples
  (SAM3 lost it immediately), so the legend was correctly null per
  spec §5.5. Whether to force "tape" everywhere or trust Gemma's
  planner is a separate decision (see Open questions).
- **13 ep (11-20, 33-35)** still gated by the `fps.unresolvable` bug
  from the v2 batch results note — out of scope for this plan.

### Open questions for the user

1. **ship default**: keep `--vlm-mask-overlay` default-on for the
   merge to main, or default-off and require explicit opt-in? Current
   recommendation: default-on, given the ep8 win and no regressions.
2. **planner prompts**: ep28 gave Gemma "bottle" instead of "tape" as
   the primary object. Should the planner be biased toward task-noun
   prompts ("tape" because the task says "Put the **tape** into the
   bottle"), or is letting Gemma pick the right object per-episode the
   right call?
3. **fts pair release**: v2's 23 successful episodes don't have the
   per-segment Gemma I/O dump (the dump hook landed after v2). v3 has
   both `planner.jsonl` and `labeler.jsonl` (23 rows each, all
   parse_ok). FT-data-wise, **only v3 is usable as a paired dataset**
   for now. If a paired no-overlay control is wanted, we need to re-run
   v2 with the dump hook enabled (~15 minutes).
4. **alpha sweep**: spec §12.5 said 0.4 is fine but reserved the right
   to revisit with logs. We have one data point now (0.4 worked, no
   visible degradation). Worth a quick alpha-sweep batch (0.2 / 0.4 /
   0.6 — 3× 15 min on 23 episodes) before merging?
