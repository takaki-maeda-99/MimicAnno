# VLM ↔ transformers 互換確認（2026-05-04）

Plan: [2026-05-04-sam3-submodule-backend-plan.md](../plans/2026-05-04-sam3-submodule-backend-plan.md) Task 12

## 環境

- Python 3.11.8, uv 0.X
- `transformers==5.6.2`（現環境にインストール済み）
- `torch==2.11.0+cu130`
- Phase 2 VLM モデル: `google/gemma-4-E2B-it`

## 検証範囲

`tests/unit/test_vlm_*.py` および `tests/unit/test_fixture_labeler.py` の **8 ファイル / 58 テスト** を実行:

- `test_vlm_auto_model_resolution.py`
- `test_vlm_config.py`
- `test_vlm_messages.py`
- `test_vlm_prompt.py`
- `test_vlm_prompt_phase3.py`
- `test_vlm_types.py`
- `test_vlm_validation.py`
- `test_fixture_labeler.py`

実モデルロードが必要なテスト（`tests/test_phase2_real_vlm.py`, `tests/integration/test_cli_vlm_device.py`）は skip — 互換確認のスコープ外。

## 結果

```
58 passed in 0.34s
```

全件 green。

## VLM コードが使用する transformers シンボル

`mimicanno/vlm_labeler.py` から（`git grep`）:

1. `import transformers`（L455） — `transformers.__version__` 等の動的 attr 参照
2. `from transformers import AutoProcessor`（L473） — プロセッサのファクトリ
3. `getattr` 経由で動的解決:
   - `AutoModelForImageTextToText`（transformers 4.45+ / 5.x）
   - `AutoModelForVision2Seq`（transformers 4.x、5.x で除去）

`vlm_labeler.py` の `_resolve_auto_model_class` は 5.x 名 → 4.x 名のフォールバックを実装済み（既存 docstring L440-453 で明示）。よって 4.45 ↔ 5.x の両側で動く設計。

## `pyproject.toml` ピンの最終決定

**変更なし** — `transformers>=5.5,<6` を維持。

理由:
- 現環境（5.6.2）で全テスト green。
- `vlm_labeler.py` は元々 4.x/5.x 双方互換だが、**現状 SAM3 backend swap の作業範囲では transformers ピンを下げる動機がない**（transformers SAM3 機能を捨てるが、依存自体は VLM のために残る）。
- 4.45 まで下限を緩める提案が plan 初稿にあったが、互換性の追加検証コスト（4.45 で実機 VLM 推論 smoke 等）の方が利得を上回る。
- `<6` 上限は将来 transformers 6.x で破壊的変更が来る可能性に備えたもの。これは維持。

## 結論

- VLM コードは現環境で問題なし。
- `pyproject.toml` の transformers 制約は据え置き。
- SAM3 backend swap で transformers SAM3 拡張に直接依存しなくなったため、将来 5.x で SAM3 関連シンボルが破壊的変更されてもこの repo の Phase 3 は影響を受けない（transformers SAM3 を import しないため）。
