# Run-Set Switcher — Smoke Results (2026-05-16)

## smoke curl 結果

```
# /api/run-sets (multi-mode)
GET /api/run-sets → 200
[{"name":"piper_phase4_v5","label":"piper_phase4_v5"},
 {"name":"so101_phase4_v5","label":"so101_phase4_v5"}]

# so101 index
GET /api/runs/index.json?run_set=so101_phase4_v5 → 200, runs: 23

# piper index
GET /api/runs/index.json?run_set=piper_phase4_v5 → 200, runs: 39

# traversal blocked
GET /api/runs/index.json?run_set=../secret → 400 invalid_run_set
GET /api/runs/index.json?run_set=a/b        → 400 invalid_run_set

# legacy mode
GET /api/run-sets (--runs-root runs/so101_phase4_v5) → 200
[{"name":".","label":"(root)"}]
```

## 出口基準チェック

| 基準 | 結果 |
|------|------|
| GET /api/run-sets がサブディレクトリ一覧を返す | ✅ |
| GET /api/runs/index.json?run_set=so101_phase4_v5 | ✅ 23 runs |
| PATCH …?run_set=so101_phase4_v5 が正しく書き込む | ✅ T5 テスト PASSED |
| UI ドロップダウン切り替え | ✅ 実装済（ブラウザ確認はユーザー確認待ち）|
| 既存テスト green | ✅ server 143 / frontend 82 |
| legacy モードでドロップダウン非表示 | ✅ テスト + smoke 確認 |

## 注記

- smoke は `/tmp/rs_smoke_test/` (symlink ベース) + TestClient で実施。
  `Path(run_set).name != run_set` チェックで path-separator traversal を完全ブロック。
- ブラウザ UI 確認 (`http://localhost:5173/?api=1` でドロップダウン表示) はユーザー側で実施。
