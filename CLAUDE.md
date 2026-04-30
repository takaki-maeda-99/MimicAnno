# MimicAnno project guidance for Claude

## Phase 5 autonomous mode (in effect 2026-04-30 →)

User directive (2026-04-30):

> 「いったんパイプライン完成して実データでのラベリングを妥当な感じでラベリングできてるの確認するところまではOpusがレビューして全部自動でやってくれていいよ。APIコストは厭わない。」

Translation / scope:
- **Autonomy window:** until the Phase 5 pipeline is complete AND a real-data labeling sanity check has passed.
- **Permitted autonomous actions during this window:**
  - Run spec review loop (spec-document-reviewer subagent) and apply fixes without user check-in.
  - Skip the brainstorming-skill user-review gate (`User reviews written spec`) and proceed directly to writing-plans.
  - Invoke writing-plans, executing-plans, subagent-driven-development without per-step user approval.
  - Spend API tokens freely on parallel subagents, code review, and verification.
  - Run the implemented `mimicanno export` (or any Phase 5 sub-project pipeline) against real data (`~/MimicRec/datasets/SO101` or similar) and inspect outputs.
- **What still requires user approval, even in autonomy window:**
  - Destructive ops with high blast radius (force-push, hard reset on shared branches, deleting user data).
  - Anything touching shared infrastructure outside this repo and `~/MimicRec/datasets/`.
- **Exit criteria for the autonomy window:**
  1. Phase 5 sub-project's exit criteria pass (per its spec).
  2. Real-data labeling smoke check confirms output looks reasonable (qualitative — phases align with what a human would expect, no obvious garbage).
  3. Hand back to user with a written summary of what shipped + what looked off + open questions.

After exit: revert to default behavior (ask before non-trivial actions; respect skill gates).

## Workflow conventions

- Use uv for Python (`uv run`, `uv add`, `uv sync`). Repo's pyproject is the source of truth.
- All work goes through superpowers skills (brainstorming → writing-plans → executing-plans / subagent-driven-development → verification-before-completion → finishing-a-development-branch).
- Spec docs live under `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`.
- Implementation plans live under `docs/superpowers/plans/YYYY-MM-DD-<topic>-plan.md`.
- Phase 1–4 are SHIPPED. Phase 5 is decomposed into sub-projects (export / persistence backend / edit UI / evaluation / MimicRec integration); each sub-project gets its own spec + plan.
