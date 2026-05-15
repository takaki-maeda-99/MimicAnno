# Phase 5 B r1 — UI smoke wrap-up plan (v3, final)

**Date:** 2026-05-15
**Scope:** complete the smoke session close-out now that all code is already in origin/main.
No new branches or PRs needed. Remaining work: memory, handoff note, service shutdown.

---

## 1. Actual state entering this wrap-up

| Item | State |
|------|-------|
| `origin/main` tip | `9f1dd06` — merge commit that includes `feat/hand-pipeline` + the 4 BLOCKER fix commits |
| 4 BLOCKER fix commits | **Already in origin/main** ✅ |
| Disk (ep0 + ep32) | Restored ✅ — ep0 run_hash = `sha256:e350611063945b4e1bce196aec7cd05162af51ff7ad6a82f854af9d081f0fb7d`; ep32 = `sha256:834aa84279bd717f49a0a127e66b7be5001c9052c3b0fef3e35fd0ceadef89a1` |
| Server tests | 112/112 ✅ |
| Frontend tests | 60/60 ✅ |
| Local branch `feat/phase5-b-r1-relabel` | Does not exist |
| Local branch `smoke/all-pr-merged` | Does not exist |
| Dev services | `mimicanno serve` on `:8765`, `vite` on `:5173` — still running |

### The 4 commits now in main

| SHA | Message |
|-----|---------|
| `2b71741` | `fix(phase5-b/r1): replaceState URL ?hash after successful PATCH` |
| `9944b44` | `fix(phase5-b/r1): reload button drops ?hash so 412 recovery succeeds` |
| `8ab858d` | `fix(phase5-b/r1): toast prefix uses server error code on generic 5xx` |
| `2d63e0a` | `docs(phase5-b/r1): UI smoke verification plan + findings summary` |

---

## 2. Step order

```
1.  Update memory (no approval needed):
    - project_phase5_status.md: mark smoke session complete;
      note 4 BLOCKER fixes merged to main at 9f1dd06
    - project_phase5_b_r1_shipped.md: append the 3 BLOCKER fix SHAs
      (2b71741, 9944b44, 8ab858d) + smoke doc SHA (2d63e0a)

2.  Write handoff note:
        docs/superpowers/notes/2026-05-15-phase5-b-r1-handoff.md
    Contents checklist:
    - Code state: all 4 BLOCKER commits in origin/main at 9f1dd06
    - 3 BLOCKER fixes with specific commit SHAs + one-line description each
    - Disk pollution status: ep0/ep32 restored (specific run_hash values above)
    - "Human hand video viewer" parking lot — new sub-project, needs spec
    - TEST-GAP: frozen tests/fixtures/ snapshot (long-term recommendation,
      not urgent)
    - Location pointer: smoke plan + findings summary at
      docs/superpowers/plans/2026-05-14-phase5-b-r1-ui-smoke-plan.md §end
    Lifecycle: leave untracked for operator to commit to main when ready.

3.  Stop dev services (REQUIRES operator confirmation — operator owns
    the SSH tunnel context and may have other processes on these ports):
        lsof -ti :8765 | xargs -r kill   # backend
        lsof -ti :5173 | xargs -r kill   # vite dev
```

Total time estimate: ~5 minutes.

---

## 3. Out of scope

- **No new branches** — all code already in main.
- **No new PR** — nothing to review; code shipped.
- **No cherry-pick operations** — would conflict and add nothing.
- **`git branch -D`** — no smoke/* branches exist; nothing to delete.
- **`gh` commands** — not needed.
- **Re-running tests** — both suites already confirmed green in prior steps.
- **"Human hand video viewer"** — new sub-project, deferred.
- **`mimicanno annotate` re-runs** — disk restore complete.

---

## 4. Acceptance criteria

Wrap-up exits when ALL of:

1. ✅ Memory updated: `project_phase5_status.md` + `project_phase5_b_r1_shipped.md` carry the smoke-session outcome and the 4 commit SHAs.
2. ✅ Handoff note written at `docs/superpowers/notes/2026-05-15-phase5-b-r1-handoff.md`.
3. ✅ `lsof -i :8765` and `lsof -i :5173` both return empty (after operator approval).
4. ✅ Operator confirms ready to close the smoke session.

---

## 5. Related artifacts

- Phase 5 B r1 spec: `docs/superpowers/specs/2026-05-13-phase5-B-edit-relabel-design.md`
- UI smoke plan + findings: `docs/superpowers/plans/2026-05-14-phase5-b-r1-ui-smoke-plan.md`
- Commit-trailer: `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`
