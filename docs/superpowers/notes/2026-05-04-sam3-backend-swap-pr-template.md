# PR draft template — SAM3 backend swap

Use as `gh pr create --draft --title "..." --body "$(cat ...)"`.

## Suggested title

```
SAM3 backend: swap transformers.Sam3* → vendored sam3 submodule native API
```

## Suggested body

```markdown
## Summary

Phase 5 sub-project. Replaces the transformers `Sam3Model` /
`Sam3Processor` / `Sam3TrackerVideoModel` plumbing with a thin wrapper
over the vendored [`sam3/`](sam3/) git submodule's request-style video
predictor (`build_sam3_video_predictor`). Drops the runtime download +
HF cache dependency for SAM 3 weights — Phase 3 now points at a local
`sam3/checkpoints/sam3.pt`.

Behind a single rewrite of `mimicanno/object_tracker/sam3_runtime.py`:
- `load(*, checkpoint, device, offload_video_to_cpu=True)` — explicit
  bpe path because sam3's editable install breaks
  `pkg_resources.resource_filename`.
- `ground_on_frame(frame, prompt)` — single-image text-prompt session
  via `NamedTemporaryFile`.
- `propagate(*, video_path, prompts_with_initial_bbox, expected_frames)`
  — **one session per prompt** (sam3 visual-prompt mode rejects
  multi-box visual prompts), round-robin merged on `frame_index`.
  `add_prompt` carries **both** the entity text and the bbox seed —
  bbox-only mode tracked 0/31 frames on real SO101 data; the combo
  fix raised it to 29/31.
- `close()` closes every still-open session and runs a single
  `torch.cuda.empty_cache()` so other models on the GPU aren't disturbed.

Other surface-level changes:
- `Propagator.run` no longer materializes a dummy frame iterator — the
  runtime owns video I/O. Hands sam3 the `expected_frames` set built
  from `_build_frame_iterator(n_frames, stride)` so the contiguous
  propagation stream is filtered down to the strided subset.
- `--sam3-offload / --no-sam3-offload` (default on) wired to
  `TrackingConfig.sam3_offload` and into the `config_hash`.
- Single-file SHA-256 cache for the multi-GB `sam3.pt` keyed by
  `(mtime_ns, size)` at `~/.cache/mimicanno/sam3-sha/` — avoids
  rehashing on every CLI invocation.
- `git grep "from transformers import Sam3"` is now empty under
  `mimicanno/`.
- pyproject `sam3` extra adds the editable submodule (via
  `[tool.uv.sources]`) and declares sam3's undeclared runtime deps
  (einops, opencv-python, av, pycocotools, hydra-core, omegaconf,
  psutil, timm, iopath, ftfy, numpy<2).

## Real-data smoke — SO101 ep0 ("Put the tape into the bottle")

| Step | Result |
|---|---|
| `SAM3Runtime.load()` on real `sam3.pt` | ✅ 19s |
| `ground_on_frame("tape")` | ✅ 2 dets, top score 0.895 |
| `propagate()` 151 frames @ stride 5 | ✅ 31/31 frames in 67.6s |
| Tape track yield | ✅ 29/31 frames (93.5%) |
| API contract violations | 0 |

Driver: `scripts/smoke_sam3_runtime_so101.py`. Full notes at
`docs/superpowers/notes/2026-05-04-sam3-smoke-results.md`.

## Tests

Full unit + integration suite green: **897 passed, 1 skipped**
(skip = opt-in real-SAM3 smoke gated on `MIMICANNO_RUN_SAM3_SMOKE=1`).

New / rewritten tests:
- `tests/unit/test_preflight_sam3.py` — sha cache (cold/warm/invalidation/
  corrupt cache / atomic write / path-agnostic key) — 12 tests
- `tests/unit/test_sam3_outputs_helpers.py` — outputs-dict helpers
  (sort/skip-invalid/lost-track/dtype-mismatch) — 16 tests
- `tests/unit/test_sam3_runtime_smoke.py` — sam3-native mock-driven
  contract tests covering load/ground/propagate/close — 20 tests
- `tests/unit/test_cli_phase3.py` — `--sam3-offload` flag propagation +
  config-hash sensitivity — +3 tests
- `tests/conftest.py` — eager `import torch` so
  `test_local_gemma_skeleton`'s `sys.modules.setdefault('torch', fake)`
  no-ops.

## Test plan

- [ ] `git submodule update --init sam3`
- [ ] `uv sync --extra sam3 --extra dev --extra vlm`
- [ ] `uv run pytest -q`
- [ ] `uv run python scripts/smoke_sam3_runtime_so101.py`
- [ ] (gated) Phase 2+3 full pipeline smoke once Gemma 4 weights land
      in HF cache; runs/<canonical>/{tracks,manifest}.json sanity-check
      via the React viewer.

## Spec / plan

- Spec: `docs/superpowers/specs/2026-05-04-sam3-submodule-backend-design.md`
- Plan: `docs/superpowers/plans/2026-05-04-sam3-submodule-backend-plan.md`
- Smoke notes: `docs/superpowers/notes/2026-05-04-sam3-smoke-results.md`
- Phase 3 spec received a 2026-05-04 redirect note; older transformers-Sam3
  details are superseded.

## Out of scope (follow-ups)

1. Phase 2 + 3 full pipeline smoke (gated on Gemma 4 weights).
2. Multi-GPU sam3 (`Sam3VideoPredictorMultiGPU`).
3. SAM 3.1 multiplex predictor adoption.
4. Switch propagation to text-only sessions, dropping the explicit
   grounding step (matches `sam3/tools/segment_video.py` pattern more
   closely; would simplify the pipeline if Phase 2 + 3 share entity
   prompts cleanly).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```
