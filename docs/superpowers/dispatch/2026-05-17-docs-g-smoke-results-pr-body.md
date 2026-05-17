# docs/g-smoke-results PR — manual creation

## URL

<https://github.com/takaki-maeda-99/MimicAnno/pull/new/docs/g-smoke-results>

Base: `main` / Compare: `docs/g-smoke-results` (tip `0ed0892`)

## Title

```
docs(g-smoke): G6 / G7 / G8 GPU smoke results notes
```

## Body

```markdown
## Summary

Adds 3 GPU smoke result notes from the 2026-05-17 morning autonomy-exit batch:

- **G6** — Gemma 4B planner 1 ep regression (`2026-05-17-g6-gemma4b-planner-smoke-results.md`, +63)
- **G7** 🟡 PARTIAL — Hand+HAMER 1 ep smoke (`2026-05-17-g7-hand-hamer-smoke-results.md`, +78). Mechanics + 3-axis overlay PASS; `cam_t` metric anchoring deferred (full-ep re-run needed)
- **G8** — UniDAC precompute_depth 1 ep smoke (`2026-05-17-g8-unidac-depth-smoke-results.md`, +47). Includes 2 plan corrections found during execution: `--no-viz` (viz default-on, not `--save-viz`), and `unidac` conda env needs `PYTHONPATH=.../UniDAC` workaround

Pure docs change. Touches master §2 contract: **no**.

## Test plan

- [x] Notes render correctly in `docs/superpowers/notes/`
- [x] 3 files added, 0 modifications, 0 deletions vs `origin/main` (verified `git diff origin/main --stat` → `3 files changed, 188 insertions(+)`)
- [x] No code touched, no test changes

## Note on this branch

Branch was rebuilt 2026-05-17 evening via `force-with-lease` from `a14059a` (commander recovery — the original branch had picked up 127-file pollution from a stale base where dozens of more recent PRs were missing). The current 3-commit branch (`922a146 → 4b14639 → 0ed0892`) is a clean re-cherry-pick of the 3 docs commits (`158b647` / `6ca0a43` / `633ca13`) onto a fresh `origin/main`. The 4th commit on the original branch (`a14059a`, a TODO.md update) was intentionally dropped: main's TODO already records G6/G7/G8 completion via commit `e70027b`, so the update is redundant.

Backup tag `backup/docs-g-smoke-pre-clean` preserves the pre-recovery tip on origin.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

## After PR is created

Reply with the PR number to commander so TODO 残り未マージ PR 待ち table can be cleared.
