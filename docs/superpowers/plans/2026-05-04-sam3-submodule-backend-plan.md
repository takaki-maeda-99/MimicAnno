# 実装計画: SAM3 backend swap to sam3 submodule native API

Date: 2026-05-04
Spec: [2026-05-04-sam3-submodule-backend-design.md](../specs/2026-05-04-sam3-submodule-backend-design.md)
Branch: `experiment/sam3-local`
Status: Ready to execute（autonomy window 中、ユーザレビュー gate スキップ）

---

## 概要

タスクは依存順に並べた 17 件、各 30〜60 分目安。`subagent-driven-development` で 1 タスク = 1 subagent を基本に進める。**早期 smoke**（Task 4）で sam3 native API の前提をブロッキング検証してから本実装に入る構成。

## 進行ルール

- **早期 smoke（Task 4）が失敗したら一時停止**してユーザに報告する。それ以降の設計が成立しないため。
- それ以外のタスク失敗は autonomy window 中なので Opus が自走で原因究明 → fix。
- 各タスク完了時に `pytest -q` を当該テストファイルだけ走らせて green を確認。最後にフルテスト。
- 並列化可能なタスクは `[parallel-ok]` でマーキング。

---

## Task 1: sam3 を editable 依存として `pyproject.toml` に追加

**Goal**: `uv sync` 後 `python -c "from sam3.model_builder import build_sam3_video_predictor"` が import 成功する。

- `pyproject.toml` の `[project] dependencies` に `"sam3"` 追加。
- `[tool.uv.sources]` に `sam3 = { path = "sam3", editable = true }` 追加。
- 既存の `transformers>=5.5,<...` ピンを `transformers>=4.45,<6` に緩和（VLM 用）。
- **sam3 の declared deps が不足しているため、明示追加が必要**（Task 4 の smoke で発覚）:
  - `einops`, `opencv-python`, `av`, `pycocotools`, `hydra-core`, `omegaconf`, `psutil`
  - これらは sam3 がランタイムで import するが sam3 の pyproject に書かれていない。MimicAnno 側で declared dep として追加。
- `numpy` の上限制約：sam3 は `numpy>=1.26,<2` を要求。`uv sync` で 1.26 系にピン。
- `uv sync` 実行。エラーなければ smoke import コマンドで確認。
- `uv.lock` も commit に含める。
- **scripts/smoke_sam3_bbox_only.py を成果物として commit**（Task 4 で作成済み、回帰テスト用に残す）。

**Out**: 上記 import が通る。`uv pip list | grep sam3` で sam3 が editable で入っている。

---

## Task 2: sam3 checkpoint preflight 整理

**Goal**: `resolve_sam3_checkpoint(Path)` が単一ファイル前提に戻り、sha256 cache が効く。

- `mimicanno/preflight.py` の `resolve_sam3_checkpoint` を spec §4.3 通りに書き直す。
- cache 場所: `~/.cache/mimicanno/sam3-sha/<mtime_ns>_<size>.txt`（key は path 別ではなく `(mtime, size)` のみ — 同 weights を別 path に置いた場合も再利用される）。
- HF snapshot dir 連結 sha のヘルパ（あれば）削除。
- `tests/preflight/test_resolve_sam3_checkpoint.py` を新規 or 更新：
  - 単一 .pt ファイルで sha が返ること
  - dir を渡したら明示エラー
  - cache hit 時に再計算が走らないこと（モック で `sha256_file` 呼び出し回数を assert）

**Out**: 該当テストファイル green。

---

## Task 3: CLI default checkpoint を `sam3/checkpoints/sam3.pt` に変更

**Goal**: `--sam3-checkpoint` のデフォルトを repo 内 submodule の sam3.pt に固定。`dir_okay=False`。

- `mimicanno/cli.py` の `--sam3-checkpoint` option：
  - `default=Path("sam3/checkpoints/sam3.pt")`
  - `type=click.Path(exists=False, dir_okay=False, file_okay=True, path_type=Path)`（exists check は preflight に任せる）
  - help テキスト更新（HF id の話を消す）
- `--sam3-offload`（default `True`）option を新規追加 — spec §4.2 / §6 の `offload_video_to_cpu` 用。
- `mimicanno/config.py` の `TrackingConfig.sam3_offload: bool` フィールド追加。`to_dict()` / re-hash には含める（再現性ハッシュへの影響を spec phase3 §9.1 のハッシュ仕様と整合させる — ハッシュ要素として **含める**。実行時オプションだが実行内容には影響しないため迷うが、明示的に hash に入れることで「offload 設定差分で結果が再現しないトラブル」を可視化できる）。
- `tracking.sam3_model_id` のデフォルトを `"sam3"` に変更（HF id 文字列はもはや意味がないため簡略化）。

**Out**: `mimicanno run --help` で `--sam3-checkpoint` と `--sam3-offload` が表示される。

---

## Task 4: 【早期 smoke】 sam3 bbox-only セッションが動くか — ✅ **2026-05-04 完了**

**Status**: smoke 実行済み、spec §9 の課題 1〜9 を確定して spec に書き戻した。残課題は §9 課題 12（実機 SO101 で frame 0 不一致が起きないか観察）のみで Task 14 に移譲。以下は再実行用のレシピ:

**Goal**: spec §9 課題 5 を解消。sam3 native API で **text なしの bbox-only セッション**が `RuntimeError` を起こさないことを実機確認。

- `scripts/smoke_sam3_bbox_only.py` を新規作成（リポジトリ root 直下、コミット対象）：
  ```python
  # 短尺 mp4（テスト用 fixture）を 1 つ用意し、frame 0 に bbox prompt を打って
  # propagate_in_video を 5 frame 程度回し、各 frame で out_obj_ids が空でないこと、
  # out_boxes_xywh の値域が [0, 1] に収まることを print。
  ```
- `~/MimicRec/datasets/SO101` の動画（短い 1 episode）を入力に使う。手元になければ `sam3/assets/` 内の `.mp4` で代替。
- スクリプトを `uv run python scripts/smoke_sam3_bbox_only.py <video> --bbox 0.3 0.3 0.2 0.2` で実行。
- 期待出力: `frame_idx=0..4, obj_ids=[0], boxes_xywh=[[...]]` の log。
- **失敗した場合**: ユーザにエスカレーション（Phase 5 autonomy window でも、設計前提を覆す問題は要相談）。
- ついでに `out_boxes_xywh` の値域を観察し、**spec §9 課題 1, 2, 3, 4**（座標規約・track lost 挙動・frame 0 yield 挙動）を確定して spec の該当セクションを「✓ 確認済み」と更新。

**Out**: smoke スクリプトが green、座標規約が spec に書き込まれる。

**Blocks**: Task 5 以降全部。

---

## Task 5: SAM3Runtime — `_outputs_to_bbox_score_list` ヘルパ + 単体テスト

**Goal**: sam3 出力 dict から `[(BBox, score), ...]` への変換ヘルパを純関数として実装。

- `mimicanno/object_tracker/sam3_runtime.py` 内の private function に追加：
  - `_outputs_to_bbox_score_list(outputs: dict) -> list[tuple[BBox, float]]`：grounding 用、score 降順ソート。空配列なら `[]`。
  - `_outputs_to_bbox_score(outputs: dict) -> tuple[BBox, float] | None`：propagate 用、obj_id=0 だけ取り出す。lost なら None。
- 座標規約は Task 4 で確定したものに合わせる。cxcywh だった場合は変換を入れる。
- `tests/object_tracker/test_sam3_runtime.py` に純関数テスト 4 件:
  - 1 obj 検出 → BBox 1 個
  - 0 obj → 空 list
  - 複数 obj → score 降順
  - BBox 範囲外（例: x>1.0）が来たら clamp（既存 BBox は範囲 assert があるので `try/except ValueError` で skip）

**Out**: 該当テスト green。`SAM3Runtime` クラス本体はまだ書き換えない（既存 transformers 経路は残しておく）。

**[parallel-ok]** with Task 6.

---

## Task 6: FixtureSAM3Tracker のシグネチャ更新

**Goal**: `mimicanno/object_tracker/fixtures.py` の `FixtureSAM3Tracker.propagate` を新シグネチャ（`video_path`, `expected_frames`）に書き換え。

- spec §5.2 の擬似コード通りに実装。
- `raise_on_propagate_at_frame` セマンティクスは維持。
- `tests/conftest.py` の fixture 構築箇所も追従。
- `tests/object_tracker/test_propagator.py` で fixture を使ってるテストの呼び出し箇所を新シグネチャに更新（**Propagator 側の本実装は Task 9 でやる**ので、fixture と test だけ先に書き換えておく）。

**Out**: fixture 単体テスト green（`tests/object_tracker/test_fixtures.py` などがあれば）。

**[parallel-ok]** with Task 5.

---

## Task 7: SAM3Runtime — `load` / `close` の差し替え

**Goal**: SAM3Runtime のクラス構造を transformers 経路から sam3 native 経路に差し替え（`ground_on_frame` / `propagate` はまだ未実装で `NotImplementedError`）。

- `__init__` 引数を `_predictor`（`Sam3VideoPredictor` インスタンス）と `_open_sessions: list[str]`、`_offload_video: bool` に変更。
- `load(*, checkpoint: Path, device: str = "cuda", offload_video_to_cpu: bool = True)`:
  - `_ensure_sam3_importable()` で `from sam3.model_builder import build_sam3_video_predictor` を試す。失敗時 `SAM3ExtrasMissing`。
  - `predictor = build_sam3_video_predictor(checkpoint_path=str(checkpoint))` を `try/except Exception` で囲み、失敗時 `SAM3InitFailed`。
  - `torch.cuda.set_device(device)` を呼ぶ（`build_sam3_video_predictor` 内部で cuda 前提なので CPU 経路は当面非対応）。
- `close()`: open sessions を全部 `close_session(run_gc_collect=False)` した後、`gc.collect() + torch.cuda.empty_cache()` を 1 回。`_closed` flag で idempotent。
- 既存 `_ensure_transformers_sam3_importable` / 旧 `__init__` 引数は削除。
- spec phase3 §2.3 の「only file importing transformers Sam3*」記述に追従して、本ファイル冒頭 docstring を「only file importing `sam3.*`」に書き換え。

**Out**: `SAM3Runtime.load(checkpoint=Path("sam3/checkpoints/sam3.pt"))` がインスタンス化に成功。close() が無例外。`pytest tests/object_tracker/test_sam3_runtime.py::test_load_close` が green。

---

## Task 8: SAM3Runtime — `ground_on_frame` 実装

**Goal**: spec §4.1 のスケッチを実装。

- `tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)` パターン。
- 最後に必ず session close & file unlink（`try/finally` の二重ネスト）。
- 戻り値は Task 5 で作った `_outputs_to_bbox_score_list`。
- ユニットテスト：`build_sam3_video_predictor` を mock して `handle_request` 呼び出しシーケンスを assert。
  - mock の return_value を `{"out_obj_ids": np.array([0]), "out_boxes_xywh": np.array([[0.1,0.2,0.3,0.4]]), "out_probs": np.array([0.9])}` 等にする。
- 1 ケースは実機 sam3 で smoke（CI から exclude する `@pytest.mark.gpu` で）。

**Out**: unit テスト green。GPU smoke は手動実行で OK。

---

## Task 9: SAM3Runtime — `propagate` 実装（round-robin merger）

**Goal**: spec §4.2 のスケッチをそのまま実装。

- N session を起動 → 各 session の stream を `iter()` で保持 → frame_idx 単位で min を取って yield。
- track lost 時の None 埋め (#10 対応)。
- `expected_frames` で間引き。
- `finally` で全 session close、リーク防止。
- ユニットテスト：mock で 2 session × 3 frame の stream を作って merge 結果を assert。
- 1 obj track lost のケース（途中から空 obj_ids で yield）も unit でカバー。

**Out**: unit テスト green。

---

## Task 10: Propagator.run の `runtime.propagate` 呼び出しを新シグネチャに更新

**Goal**: spec §3.2 の通り `frames=Iterator[...]` 廃止、`video_path` + `expected_frames` を渡す。

- `propagator.py:399-423` を修正。
- `_build_frame_iterator(n_frames, stride)` の結果を `set` 化して `expected_frames` に渡す。
- TODO(Task 19) コメント削除。
- `Propagator.run()` のシグネチャは既に `video_path` を受けているので呼び出し側 `pipeline.py:850-857` は無変更でいけるはず（要確認）。
- `tests/object_tracker/test_propagator.py` の Task 6 で書き換えた呼び出し箇所が green であることを確認。

**Out**: propagator 関連テスト green。

---

## Task 11: spec phase3 を更新（§2.3, §2.5, §8）

**Goal**: `2026-04-28-mimicanno-phase3-sam3-tracking-design.md` 内の transformers 前提記述を本 spec で上書き。

- §2.3「`SAM3Runtime` は transformers.Sam3* をいれる唯一のファイル」→ 「sam3 submodule の `sam3.*` をいれる唯一のファイル」。
- §2.5 preflight の checkpoint 解決ルールを単一ファイル sha + cache に書き換え。
- §8 が transformers 関連の制約を述べていれば書き換え。
- 旧 spec のヘッダに `> [2026-05-04 update] §X.Y は本 spec の決定で上書きされた。詳細: docs/superpowers/specs/2026-05-04-sam3-submodule-backend-design.md` の note を入れる。

**Out**: 旧 spec が新 spec と矛盾しない状態。

**[parallel-ok]** with Task 12〜13.

---

## Task 12: VLM (Phase 2) の transformers 互換確認

**Goal**: spec review #13。`mimicanno/vlm_labeler.py` が `transformers>=4.45` で動くことを実機確認。

- 既存 Phase 2 unit/integration テスト（`tests/vlm/test_vlm_labeler.py` など）を実行。
- 失敗するなら最低バージョンを上げて pin を `>=4.X` に調整。
- 実機 VLM 推論（Phase 2 smoke）は時間がかかるので、autonomy window 中なら 1 episode の Phase 2 までを 1 回回す。

**Out**: テスト green、`pyproject.toml` の transformers pin が確定。

**[parallel-ok]** with Task 11, 13.

---

## Task 13: 全 unit テスト + integration テスト green

**Goal**: `uv run pytest -q` がフル green。

- 並行作業で残った fixture/モック未対応箇所を潰す。
- 旧 transformers モックを使っていたテスト（あれば）を sam3 native モックに置き換え。
- `git grep -n "from transformers import Sam3"` の結果が **空** であることを確認（spec §10 完了基準 #4）。

**Out**: フルテスト green。

---

## Task 14: 実データ smoke on SO101

**Goal**: spec §10 完了基準 #1, #2 を満たす。

- `~/MimicRec/datasets/SO101` から 1 episode を選び：
  ```bash
  uv run mimicanno run --target-phase 3 \
      --video <episode>.mp4 \
      --output /tmp/sam3-smoke/<episode>/ \
      --sam3-checkpoint sam3/checkpoints/sam3.pt
  ```
- 完走確認、`tracks.json` が生成されること。
- viewer で開き、bbox がオブジェクトに追従しているかを目視（既存 viewer は `mimicanno serve` などのコマンド or static html）。
- 「妥当」かどうかの判断は、人間が見て (a) 主要オブジェクトに bbox が乗っている、(b) 無関係領域に bbox が散らばってない、(c) 中盤〜終盤で bbox が暴走してない、の 3 点で OK とする。

**Out**: smoke 結果のスクリーンショットなり log なりを `docs/superpowers/notes/2026-05-04-sam3-smoke-results.md` に貼る。

---

## Task 15: チェックリスト & ドキュメント

- README / docs に SAM3 setup 手順（`git submodule update --init && uv sync`）を追記。
- `CLAUDE.md` の Phase 5 autonomy window 出口条件チェックを更新（「SAM3 backend swap shipped, real-data smoke passed」をチェック）。

**Out**: README に手順あり、CLAUDE.md に進捗。

---

## Task 16: branch 整理 & PR draft

**Goal**: `experiment/sam3-local` を main に向けて PR ドラフト化（merge は user 判断）。

- `git rebase main` で取り込み（衝突あれば解消）。
- コミット粒度を整える（必要なら `git rebase -i` 相当の作業 — ただし interactive flag は禁止なのでチェリーピックで）。
- `gh pr create --draft` で本 spec / plan を summary にリンク。

**Out**: PR draft URL を user に提示。**マージは user 承認待ち**（autonomy window でも shared infra 影響扱い）。

---

## Task 17: 後追い課題の memory / project note 化

**Goal**: 残った非クリティカル課題を将来の自分のために記録。

- 「stride 計算量最適化（疑似 stride で N 倍速）」を `docs/superpowers/specs/` の改善候補に追記。
- 「grounding 用 image predictor 分離」も同様。
- spec §9 で確定しなかった項目（あれば）を memory `project` type にメモ。

**Out**: 後追い改善が消えない仕組みになっている。

---

## ロールバック

- 各タスクは git commit を細かく刻む（タスク 1 つ = 1〜3 commit）。
- もし Task 14 smoke が失敗 → spec 段階に戻して redesign。`git revert` で commit 単位の戻しが効くようにしておく。
- 最終的に main は `1b180b5` のまま。`experiment/sam3-local` がダメなら捨てる。

## 完了の判定

- [ ] Task 1〜13 すべて green
- [ ] Task 14 smoke が「妥当」
- [ ] `git grep "from transformers import Sam3"` 空
- [ ] PR draft 作成済み

これらが満たされた時点で **Phase 5 autonomy window の SAM3 部分は完了**。出口報告書（CLAUDE.md autonomy window 出口条件 #3）を user に提出。

---

## 実行戦略（v2 — 2026-05-04 確定）

Task 4 smoke が完了し設計前提が固まった。残 Task 1〜3, 5〜17 を **並列実行可能性 + 依存関係 + リスク** で並べ替え、波（wave）単位で進める。

### 依存グラフ

```
Task 1 (pyproject editable + missing deps)
   ├── blocks: 7 (load uses sam3 import)
   └── blocks: 14 (smoke needs install)
Task 2 (preflight single-file sha + cache)        [独立]
Task 3 (CLI default ckpt + --sam3-offload)
   └── depends on: 1 (config.py の TrackingConfig 変更を Task 1 と同時に触ると衝突しやすい)
Task 5 (純関数ヘルパ _outputs_to_*)               [独立]
Task 6 (FixtureSAM3Tracker.propagate 改修)        [独立]
Task 7 (SAM3Runtime.load/close + class skeleton)
   └── depends on: 1
Task 8 (SAM3Runtime.ground_on_frame)
   └── depends on: 5, 7
Task 9 (SAM3Runtime.propagate)
   └── depends on: 5, 7
Task 10 (Propagator → expected_frames signature)
   └── depends on: 9, 6
Task 11 (旧 spec phase3 §2.3/§2.5/§8 更新)        [独立、doc のみ]
Task 12 (VLM transformers compat smoke)           [独立]
Task 13 (全テスト green sweep)
   └── depends on: 1〜10
Task 14 (real-data smoke on SO101)
   └── depends on: 13
Task 15 (README/CLAUDE.md 更新)
   └── depends on: 14
Task 16 (PR draft)
   └── depends on: 15
Task 17 (memory note 化)                          [最後]
```

### 波（wave）と並列実行プラン

#### Wave 1（並列、最大 6 本）— 周辺整備

inline で進めるもの（Opus 自身がやる、subagent 不要な小タスク）:
- **Task 1**: pyproject.toml 編集、`uv sync`、import smoke。
- **Task 11**: 旧 spec phase3 への 2026-05-04 update note 追記（doc のみ、機械作業）。

subagent に投げる（並列 4 本）:
- **Task 2**: `general-purpose` subagent で preflight rewrite + テスト追加（独立）
- **Task 5**: `general-purpose` subagent で純関数ヘルパ + テスト（既存 ファイルに追記、本体クラスは触らない）
- **Task 6**: `general-purpose` subagent で FixtureSAM3Tracker.propagate 改修 + 呼び出し側更新
- **Task 12**: `general-purpose` subagent で Phase 2 VLM unit テストを現環境（transformers 5.6.2）で実行し最低互換バージョンを記録

**Wave 1 完了基準**: 4 つの subagent が green で帰還、Task 1/11 が手元で commit 済み。`uv sync` 成功、`uv run pytest tests/preflight tests/object_tracker/test_sam3_runtime.py::<helper test> tests/vlm` が green。

**Wave 1 後の go/no-go チェック**: 
- 1 つでも subagent が未解決 issue を残したら、**Wave 2 に進まず原因切り分け**。
- 特に Task 2 で sha cache の lock 設計を間違えると並行起動でレース → CIで flaky。再レビュー要。

#### Wave 2 — CLI/Config 層

inline:
- **Task 3**: CLI default ckpt 変更 + `--sam3-offload` オプション追加 + `TrackingConfig` フィールド追加。 

直列で 1 タスクのみ。Task 1 で uv sync が安定したことを前提にする。

**Wave 2 完了基準**: `mimicanno run --help` で新オプション表示、`pytest tests/cli` green。

#### Wave 3 — SAM3Runtime 本体差し替え

inline で順次実行（Opus 自走）:
- **Task 7**: SAM3Runtime クラス skeleton（load + close、ground_on_frame と propagate は `NotImplementedError`）。bpe_path 明示渡しを忘れない（spec §9 #7）。

完了後、**並列 subagent 2 本**:
- **Task 8**: ground_on_frame 実装（spec §4.1 通り、NamedTemporaryFile）
- **Task 9**: propagate 実装（spec §4.2 通り、N session round-robin merger）

**Wave 3 完了基準**: 
- `tests/object_tracker/test_sam3_runtime.py` の Runtime クラステスト（mock based）green
- `git grep "from transformers import Sam3" mimicanno/` 結果が空

**Go/no-go**: Wave 3 は本作業のクリティカルパス。失敗時は spec の §4.1 / §4.2 を見直し → user 報告。

#### Wave 4 — 結合

inline:
- **Task 10**: Propagator.run() の `runtime.propagate()` 呼び出しを新シグネチャに変更（`expected_frames=set(_build_frame_iterator(...))`）

直列 1 タスク。

#### Wave 5 — 検証

inline:
- **Task 13**: フルテスト green。`uv run pytest -q` で全 green を確認。残った fixture/モック未対応箇所を潰す。

#### Wave 6 — 実機検証（最重要 go/no-go）

inline:
- **Task 14**: SO101 1 episode で `mimicanno run --target-phase 3` を実行 → viewer 目視。

**autonomy window 出口条件**:
- pipeline 完走 → ✓
- track が「人間が見て妥当」 → ✓ なら次へ進む
- 「妥当」でない → spec 戻し / Wave 3 のロジック再点検

#### Wave 7 — 出荷準備

inline:
- **Task 15**: README / CLAUDE.md 更新
- **Task 16**: `gh pr create --draft` で PR ドラフト作成、本 spec/plan をリンク
- **Task 17**: 後追い改善メモを memory に記録

**user 介入が必要な最終ステップ**: PR の **merge** は user 承認待ち（autonomy window でも shared infra 影響扱い、CLAUDE.md 例外条項）。

### コミット境界（git）

各 Task = 1 commit を原則とし、以下の prefix で分類:

- `chore(deps): ...` — Task 1
- `feat(preflight): ...` — Task 2
- `feat(cli): ...` — Task 3
- `refactor(sam3_runtime): ...` — Task 5, 7, 8, 9
- `refactor(propagator): ...` — Task 10
- `refactor(test-fixtures): ...` — Task 6
- `docs(spec): ...` — Task 11
- `test(vlm): verify transformers >=4.45 compat` — Task 12
- `test: green full suite` — Task 13（テスト fix が混じる場合）
- `docs(notes): SO101 smoke result` — Task 14（log を notes に貼る）
- `docs(readme): SAM3 setup` — Task 15

`git revert <sha>` で機能単位の戻しが効くように粒度を保つ。

### 中断条件（halt-and-report）

以下のいずれかが起きたら **Opus は止まり user 報告**:

1. Task 1 の `uv sync` が解決不能（依存衝突 or sam3 自体のバグ）。
2. Task 9 round-robin merger が実機で frame_idx 不整合（spec §9 #6 の前提崩れ）。
3. Task 12 で VLM が transformers 5.6.2 でも動かない／互換 break が大規模。
4. Task 14 SO101 smoke で「明らかに妥当でない」結果（bbox が暴走、phase 3 すら通らない、等）。

それ以外の小規模失敗（テスト 1 件落ち、import エラー、型不一致 etc.）は autonomy window 中なので Opus が自走で fix。

### 期待所要時間（目安）

- Wave 1: 並列 30〜45 分（subagent 律速）
- Wave 2: 15 分
- Wave 3: 60〜90 分（本体実装）
- Wave 4: 15 分
- Wave 5: 30 分（テスト fix 含む）
- Wave 6: 30〜60 分（GPU 推論時間 + 目視）
- Wave 7: 20 分

合計: **3〜5 時間**（GPU 推論時間込み、API トークン消費は autonomy window で許容）。
