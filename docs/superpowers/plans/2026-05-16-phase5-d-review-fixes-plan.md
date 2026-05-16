# Phase 5 D — Review-fix plan (2026-05-16)

**Branch:** `feat/phase5-d-eval-harness` (continuing)  
**Scope:** Address 2 items from adversarial review before merge to main.  
**Out of scope:** D r2 items (schema_version migration, focusout discard, clock-skew clamp, extra tests).

---

## Fix 1 — `reviewed` route extra-key validation parity

**Problem:** `routes.py` PATCH `.../reviewed` accepts unknown body keys silently. The other 3 routes (phase / boundary / labels) reject them via a `_ALLOWED_KEYS` superset check. A client typo like `client_edit_duration_seconds` is dropped on the reviewed endpoint only — user thinks they recorded a duration, but they didn't.

**File:** `mimicanno/server/routes.py` (reviewed PATCH route, ~line 400s; locate via `grep -n "reviewed" routes.py`)

**Change:** Add the same key-allowlist guard the other 3 routes use:

```python
_REVIEWED_REQUIRED_KEYS = {"reviewed"}
_REVIEWED_OPTIONAL_KEYS = {"client_edit_duration_ms"}
_REVIEWED_ALLOWED_KEYS = _REVIEWED_REQUIRED_KEYS | _REVIEWED_OPTIONAL_KEYS
```

Then in the route, after parsing body:
```python
if (
    not isinstance(body, dict)
    or not _REVIEWED_REQUIRED_KEYS.issubset(body.keys())
    or not body.keys() <= _REVIEWED_ALLOWED_KEYS
):
    raise MimicAnnoHTTPError(
        status=400, code="invalid_body",
        message="body must contain {'reviewed': bool} with optional 'client_edit_duration_ms'",
    )
```

The existing `isinstance(body.get("reviewed"), bool)` check stays as a follow-on type check.

**Test:** Add 1 test to `tests/server/test_routes_patch_reviewed_history.py`:
- `test_reviewed_unknown_key_400`: PATCH body `{"reviewed": true, "client_edit_duration_seconds": 5000}` → 400 invalid_body

---

## Fix 2 — Spec/code drift on eval CLI flags

**Problem:** `docs/superpowers/specs/2026-05-16-phase5-d-eval-harness-design.md` rev4 lists `--out` and `--format both` as shipped, but the CLI has neither. The rev4 note "documenting what shipped" makes this drift especially load-bearing — future readers will trust the spec.

**Decision (recommend option A):**

- **A. Trim spec to match code** (1-line edit): change `--format markdown|json|both` → `--format markdown|json`; drop the `--out` row.
- **B. Implement `--out PATH` + `--format both`**: ~15 lines in `cli.py`. Trivial to add but expands scope.

Going with **A** — eval output piping (`> file.md`) already works for the markdown path; `--out` is convenience only and can be re-added when needed (with a test).

**File:** `docs/superpowers/specs/2026-05-16-phase5-d-eval-harness-design.md`

**Change:**
1. Find the "what shipped" / CLI-flags section listing `--out` and `--format both`
2. Remove the `--out` mention
3. Change format values to `markdown|json`
4. Add a one-line note: "Deferred to D r2: `--out PATH`, `--format both` (split outputs)"

---

## Execution order

1. Fix 1 — edit `routes.py`, add test, run pytest for `tests/server/test_routes_patch_reviewed_history.py`
2. Fix 2 — edit spec file
3. Run `uv run pytest tests/server/ -q` to confirm no regressions
4. Commit: `fix(phase5-d): reviewed-route extra-key parity + spec/CLI flag drift`

## Out of scope (do NOT do here)

- `schema_version` migration on PATCH
- `focusout` discard wiring in frontend
- `Math.max(0, ...)` clock-skew clamp
- "PATCH twice → history order" test
- `edited_at` ISO format assertion test
- `runs_root` does-not-exist warning
- `--run NAME` no-match warning

These are D r2 candidates — log them in TODO.md when merging, don't tackle now.
