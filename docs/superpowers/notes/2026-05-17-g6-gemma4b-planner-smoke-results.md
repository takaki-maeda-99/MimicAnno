# G6 Gemma 4B planner 1 ep regression smoke — 結果

- **実行日**: 2026-05-17
- **env**: `.venv` (uv) `/misc/dl00/gayagaya/MimicAnno/.venv/bin/python`, torch `2.11.0+cu130`
- **GPU**: index 2 (CUDA_VISIBLE_DEVICES=2; `torch.cuda.is_available()=True`, device_count=4)
- **入力**: SO101 `episode_000000` (`--start 0 --end 0`)
- **出力**: `/tmp/g6_smoke/` (BATCH_RUNS_ROOT)
- **ログ**: `/tmp/g6_smoke.log`
- **モデル**: `/home/gayagaya/gemma_project/models/gemma-4-E4B-it:03449c82135c62749026e737a5d393f4fab212ee` (annotation.json `model_versions.vlm` より)

## 実行コマンド

```bash
.venv/bin/python scripts/batch_annotate_4B.py --help  # 引数確認
BATCH_RUNS_ROOT=/tmp/g6_smoke CUDA_VISIBLE_DEVICES=2 \
  .venv/bin/python scripts/batch_annotate_4B.py \
  --dataset so101 --start 0 --end 0 --gpu 2 \
  2>&1 | tee /tmp/g6_smoke.log
```

`batch_annotate_4B.py --help` で確認した実引数は plan の想定 (`--dataset`, `--start`, `--end`, `--gpu`) と一致。

## チェックリスト判定

| 検証項目 | 結果 | 根拠 |
|---|---|---|
| env gate (`torch.cuda.is_available()`) | ✅ | True / device_count=4 (G3/G4 blocker は再発せず) |
| `batch_annotate_4B.py --start 0 --end 0` が完走 | ✅ | exit 0、ログ末尾 `summary: ok=1, fail=0, skip=0` (83.7s) |
| 出力 artifact が生成 | ✅ | `episode_000000__62d2cc92f32f/{annotation,boundaries,tracks,signals,manifest}.json` + `video.mp4` + `index.json` |
| `_vlm_dumps/` が生成 | ✅ | `_vlm_dumps/episode_000000/_planner/call_000/{prompt,response}.txt + frame.png` + `s_001/attempt_1/{prompt,request,response,keyframe_0..3}.{txt,json,png}` |
| JSONL スキーマが baseline と互換 | ⚠️ → ✅ | `_vlm_dumps/**/*.jsonl` は **存在しなかった** (per-call ディレクトリで `request.json` / `response.txt` 形式に変わっている)。代わりに `annotation.json.segments[*]` を確認、`segment_id` / `phase` / `object` / `start_time` / `end_time` / `overall_confidence` / `evidence` / `label_version` 等の必須キーは全て埋まっており、schema_version `0.3.0`、`label_version=manipulation.v1` |
| verb (phase) 語彙が baseline 範囲内 | ✅ | `approach_object` のみ (baseline 想定の `approach/grasp/transport/release_object` family の一員) |
| object 語彙が baseline 範囲内 | ✅ | `yellow tape` のみ (SAM3 prompt と一致) |

## planner 出力 (call_000/response.txt)

```json
{"objects": ["yellow tape", "white and green cylindrical bottle"],
 "targets": [],
 "tools": ["robotic claw"]}
```

セグメント単位の attempt 出力 (s_001/attempt_1/response.txt):

```json
{"phase": "approach_object", "verb": null, "object": "yellow tape",
 "target": null, "vlm_confidence": 0.9,
 "evidence": "Claw approaches yellow tape on the table."}
```

## baseline ([[project_gemma4b_planner_smoke]]) との差分

- 語彙: baseline と完全一致 (`approach_object` + `yellow tape`)。E4B-it 出力は依然として hardcoded smoke と同一語彙圏で、SAM3-friendliness の改善は引き続き未確認 — これは G6 のスコープ外 ([[project_gemma_ft_pipeline]] により別案件)。
- データ形式の違い: dump レイアウトが **JSONL から per-call ディレクトリ構造** (`call_000/{prompt,response}.txt` + `attempt_N/request.json`) に変わっている。baseline note `project_gemma4b_planner_smoke` が JSONL を前提に書かれていたなら、その記録は古い。SFT pipeline 側 ([[project_gemma_ft_pipeline]]) が dump レイアウト変更に追随できているかは別途要確認 (FT loop 責務、本 smoke のスコープ外で **open question** として残す)。
- planner が `bottle` を `objects` に挙げているのは新規 (実映像に映っていれば妥当)。ただし最終 segment には拾われていない (1 segment / yellow tape only)。

## 結論

**PASS**: Gemma 4B planner は SO101 ep0 で regression なく完走。スキーマ break なし、verb / object 語彙は baseline 範囲内、`.venv` env も今回は CUDA OK。`.venv` torch 2.11.0+cu130 vs driver 12.6 の env risk は本セッションでは顕在化せず。

Open questions (本 smoke スコープ外):
1. `_vlm_dumps` が JSONL 形式から per-call ディレクトリ形式に切り替わっている件、SFT pipeline の loader が両形式対応済みか。
2. planner が候補に挙げた `bottle` が segment 化されない件は label_source / object_state 側の filter による可能性、FT loop が拾うべきデータかは別 spec。
