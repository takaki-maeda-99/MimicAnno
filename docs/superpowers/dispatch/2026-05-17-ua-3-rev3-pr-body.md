# U-A3 rev3 schema fix PR — manual creation

This is a **follow-up to PR #14** (U-A3 main implementation) that aligns the shipped `vlm_dumps.py` field names to match master spec rev3 §2.4. PR #14 was merged against an intermediate (rev2-like) schema; this PR corrects the drift.

## URL

<https://github.com/takaki-maeda-99/MimicAnno/pull/new/feat/ua-3-vlm-panel-rev3>

Base: `main` / Compare: `feat/ua-3-vlm-panel-rev3` (commit `3c1d7a2`)

## Title

```
feat(ua-3): correct VLM dumps viewer to master §2.4 rev3 schema
```

## Body

```markdown
## Summary

Follow-up to PR #14 (U-A3 main). PR #14 shipped a `vlm_dumps.py` + `VlmPanel.tsx` that used a schema close to but not matching master spec rev3 §2.4 (commit `eb389ba`). This PR aligns the code to the frozen rev3 contract.

**Field changes in `vlm_dumps.py`:**
- `kind`: `"planner" | "segment"` → `"planner" | "labeler"`
- `call_id` planner: `"_planner/call_NNN"` → `"call_NNN"`
- `call_id` labeler: `"s_NNN/attempt_M"` → `"s_NNN__attempt_M"` (double underscore)
- Added: `segment_ordinal`, `attempt`, `frame_url` (planner), `keyframe_urls: list[str]` (labeler), `request_json` (labeler)
- Removed: `phase`, `segment_id`, `ms`, `model_variant`
- `failed` (labeler): now `True` for ALL non-final attempts (rev3: "later attempt_M+1 exists"), not just JSON parse errors

**Frontend updates:**
- `VlmPanel.tsx` filters by `kind === "labeler"` for segment-side highlighting
- Highlights by `segment_ordinal` (with caveat: ordinal is at planner time, not post-edit segment_id)
- Shows `frame_url` for planner calls, `keyframe_urls` (multiple) for labeler attempts
- Renders `request_json` expandable panel for labeler

Touches master §2 contract: **no** (rev3 §2.4 is the frozen reference; this PR implements it)

## Test plan

- [x] `uv run pytest tests/server/ -v` — 339 pass (was 307 before U-A3 rev3 work; +32 new in `test_vlm_dumps.py` covering rev3 schema)
- [x] `uv run mypy --strict mimicanno/server/` — clean
- [x] `cd frontend && npm test` — 161 pass (+11 new `VlmPanel.test.tsx` rev3 cases)
- [ ] Manual smoke on a real SO101 run: open VLM tab, verify planner + labeler entries render correctly, segment highlight follows selection

## Files changed (6)

- `mimicanno/server/vlm_dumps.py` (rewrite)
- `mimicanno/server/routes.py` (serializer alignment + run_set forwarding)
- `frontend/src/lib/vlmClient.ts` (types)
- `frontend/src/components/VlmPanel.tsx` (rev3 fields + render)
- `tests/server/test_vlm_dumps.py` (+32 new rev3 tests, removed 7 old rev2)
- `frontend/src/components/__tests__/VlmPanel.test.tsx` (+11 rev3 tests)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

## After PR is created

Reply with the PR number to commander.
