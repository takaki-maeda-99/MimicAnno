# PR creation index — 2026-05-17 (5 pending PRs for U-A initiative)

`gh` CLI not installed, no `GITHUB_TOKEN`. Commander cannot create PRs. User creates each manually via the URLs below. Each PR body file has the Title + Body ready to copy-paste.

## Pending PRs (suggested merge order)

| Order | Sub-project | Branch | URL | Body file |
|---|---|---|---|---|
| 1 | **U-A1 follow-up routing** | `feat/ua-1-followup-routing` | <https://github.com/takaki-maeda-99/MimicAnno/pull/new/feat/ua-1-followup-routing> | `docs/superpowers/dispatch/2026-05-17-ua-1-followup-pr-body.md` |
| 2 | **U-A2 dataset summary** | `feat/ua-2-dataset-summary` | <https://github.com/takaki-maeda-99/MimicAnno/pull/new/feat/ua-2-dataset-summary> | `docs/superpowers/dispatch/2026-05-17-ua-2-pr-body.md` |
| 3 | **U-A3 rev3 schema fix** | `feat/ua-3-vlm-panel-rev3` | <https://github.com/takaki-maeda-99/MimicAnno/pull/new/feat/ua-3-vlm-panel-rev3> | `docs/superpowers/dispatch/2026-05-17-ua-3-rev3-pr-body.md` |
| 4 | **U-A4 mask overlay** | `feat/ua-4-mask-overlay` | <https://github.com/takaki-maeda-99/MimicAnno/pull/new/feat/ua-4-mask-overlay> | `docs/superpowers/dispatch/2026-05-17-ua-4-pr-body.md` |
| 5 | **U-A5 progress badge** | `feat/ua-5-progress-badge` | <https://github.com/takaki-maeda-99/MimicAnno/pull/new/feat/ua-5-progress-badge> | `docs/superpowers/dispatch/2026-05-17-ua-5-pr-body.md` |

## Conflict notes (merge order matters)

- **U-A1 follow-up (#1)** and **U-A5 (#5)** both modify `frontend/src/App.tsx` to add `?page=` routing. Merge #1 first; #5 will then need a small rebase (the App.tsx hunks should overlap as a superset).
- All other PRs touch disjoint files.

## Required PR body line (司令塔 contract drift 監視)

Every PR body MUST include the line:
```
Touches master §2 contract: no
```
(or `yes` with diff proposal, but none of these 5 PRs change §2 — confirmed).

## Procedure per PR

1. Open URL → "Create pull request" form opens
2. Copy Title from body file → paste into Title field
3. Copy Body block (between ```` ```markdown ```` and the closing ```` ``` ````) from body file → paste into Body field
4. Click "Create pull request"
5. Note the PR number, reply to commander

## After all 5 merged

Commander updates TODO U-A state column for each to `merged` and `git stash drop` the residual stashes (`stash@{0}` through `stash@{6}`, all rev2-era or other-session leftovers).
