# Contributing

## Third-party license maintenance

`NOTICE` and `THIRD_PARTY_LICENSES` are maintained by hand. Do not introduce
auto-generation tools (`pip-licenses`, `license-checker`, `cargo-about`,
`go-licenses`, etc.) without first updating this policy.

When adding a new third-party dependency, the same PR must:

- [ ] Append the dependency's full license text to `THIRD_PARTY_LICENSES`
- [ ] Append a short attribution line to `NOTICE` (name, version, license, URL)
- [ ] Verify the license is compatible with commercial redistribution
- [ ] Reference this checklist in the PR description
- [ ] Confirm `tests/test_license_hygiene.py` still passes

When removing a third-party dependency, the same PR must:

- [ ] Remove the dependency's entry from `THIRD_PARTY_LICENSES` and `NOTICE`
- [ ] Remove any submodule registration in `.gitmodules`
- [ ] Confirm `tests/test_license_hygiene.py` still passes

## Planning artifacts

`docs/superpowers/` is a gitignored working area. It is the conventional
location for design specs (`docs/superpowers/specs/`), implementation plans
(`docs/superpowers/plans/`), and session notes (`docs/superpowers/notes/`),
but **none of these files are tracked by git**. They exist to support
iteration on a single developer's machine and to be pasted into PR
descriptions when needed.

- Do **not** run `git add -f` on any path under `docs/superpowers/`.
- Do **not** propose lifting the gitignore rule without first agreeing with
  the project owner on a permanent records policy.
- When a planning document carries information that should outlive a PR
  cycle, copy the relevant content into one of the following permanent
  locations: the PR description, the squashed commit message body,
  `CONTRIBUTING.md`, a module-level docstring, or `README.md`.

This policy keeps shipped-phase planning artifacts out of the source tree
and prevents accidental capture of working-tree forbidden tokens by the
license-hygiene gate (see `tests/test_license_hygiene.py`).
