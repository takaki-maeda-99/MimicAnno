# loadable_run — frozen test fixture

This directory contains a frozen normalized copy of a real SO101 v5 run
(`episode_000000__e35061106394`) plus its `index.json`. Used by
`tests/server/conftest.py::_build_loadable_fixture()` to provide
`tmp_runs_root_loadable` and `tmp_parent_runs_root_loadable` without
depending on `runs/so101_phase4_v5/`.

## Files

| file              | purpose                                           |
|-------------------|---------------------------------------------------|
| `manifest.json`   | canonical_name 注入済、video artifact 除外済     |
| `annotation.json` | run_hash は manifest と一致                       |
| `boundaries.json` | Phase 1 boundary candidates                       |
| `signals.json`    | per-channel signal arrays                         |
| `tracks.json`     | SAM3 mask tracks                                  |
| `index.json`      | single-row index matching the run above           |

## When to regenerate

`MANIFEST_SCHEMA_VERSION` / `ANNOTATION_SCHEMA_VERSION` /
`INDEX_SCHEMA_VERSION` のいずれかが上がる PR では、本 fixture も同じ PR
で更新する。

## Regeneration

新実装の `_build_loadable_fixture()` は frozen fixture をコピーするだけ
なので、再生成には `git log -p tests/server/conftest.py` で旧
`_build_loadable_fixture` の mutation ロジックを参照すること。

spec: `docs/superpowers/specs/2026-05-16-loadable-run-fixture-design.md` §3
にも生成スニペットを記録してある。要約:

1. dev box で SO101 v5 ep0 を annotate 済の状態にする。
2. 旧 `_build_loadable_fixture` (git history から復元) を一度だけ走らせ、
   出力 5 JSON + `index.json` を本ディレクトリにコピーする。
3. `git diff` を確認してコミット。
