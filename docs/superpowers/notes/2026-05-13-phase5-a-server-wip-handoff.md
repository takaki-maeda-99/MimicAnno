# Phase 5 A — read-only persistence server: 作業中 WIP

Date: 2026-05-13
Branch: `feat/phase4-smoother-source-aware-merge` (Phase 5 A 開始 commit が
0ec9c90 / 525e041 として既に積まれている)

---

## ⚠️ 他作業との衝突回避 — 触らないこと

下記のファイル / ディレクトリは **別作業セッションで現在開発中** です。
別の作業 (例: Claude の autonomous loop, 他の Phase 作業, リファクタ) が
これらに手を出すと **未 commit の WIP を上書きしてしまう** 恐れがあるため、
このノートに気づいたら **読むだけにして編集しないこと**。

### 占有中ファイル (このノート時点で untracked)

```
mimicanno/server/
├── __init__.py         (空, placeholder)
├── errors.py           79 行  HTTP error envelope (spec §3.6)
├── routes.py           72 行  /api/runs/* + /healthz
└── runs_repo.py       117 行  RunsRepository

tests/server/
├── __init__.py
├── conftest.py        126 行
├── test_errors.py      99 行
├── test_routes.py     249 行  ← 2 failing tests あり
└── test_runs_repo.py  190 行
```

### 触っていい範囲

- **読むだけ**: 内容把握、レビュー、依存関係調査 → OK
- **隣接する別ファイルの修正**: `mimicanno/server/` の外なら OK
- **このノートへの追記**: `## 追記 (yyyy-mm-dd)` で末尾に状況メモを足すのは OK

### 触ってはいけない範囲

- 上記 untracked ファイルの編集・削除
- `mimicanno/server/` 配下に新規ファイル追加
- `tests/server/` 配下のテスト追加・修正
- `pyproject.toml` の `[server]` extra (既に commit 0ec9c90 で固まっている)
- spec / plan ドキュメント (既に commit 525e041 にある):
  - `docs/superpowers/specs/2026-05-12-phase5-A-persistence-backend-design.md`
  - `docs/superpowers/plans/2026-05-12-phase5-A-persistence-backend-plan.md`

これらに手を出す必要が出てきたら、まず **このノートの作業者 (= 主に
ユーザー本人 / Phase 5 A セッション) に確認** すること。

---

## 現状サマリ

### 既に commit 済み (ブランチに乗っている)

| commit | 内容 |
|---|---|
| `525e041` docs(phase5-a) | spec + plan for read-only persistence backend |
| `0ec9c90` build(phase5-a) | `[server]` extra (fastapi+uvicorn) + httpx dev |

### 未 commit (untracked, 上記「占有中ファイル」)

- 4 ソース + 5 テスト
- `RunsRepository` の核 (artifact allow-list, canonical_name 検査,
  traversal guard, 100ms × 3 retry for publish dir-gap)
- routes: `GET /api/runs/index.json`, `GET /api/runs/{name}/{artifact}`, `GET /healthz`
- HTTP error envelope `{"error": "<code>", "message": "<human>"}`

### テスト状況

```bash
uv run pytest tests/server/ -q
→ 31 passed, 2 failed
```

### failing test の中身

#### `test_6_get_boundaries_200`

```python
assert "etag" not in {k.lower() for k in r.headers}
AssertionError: 'etag' is in {..., 'etag', ...}
```

非 manifest アーティファクト (boundaries.json 等) は `FileResponse` で
ストリーム配信する設計だが、Starlette `FileResponse` が ETag を自動付与する。
spec §3.3 では manifest だけが ETag 持ちのはず。

修正候補:
1. `FileResponse(..., headers={"etag": ""})` で抑制
2. spec を緩めてテストを更新
3. ストリームでも独自 ETag を再計算

#### `test_16_head_manifest`

```python
assert 405 == 200
```

HEAD `/api/runs/{name}/manifest.json` が 405 を返す。`@router.get()` のみ
許可しているため。

修正候補: `add_api_route(..., methods=["GET","HEAD"])` で manifest ルートだけ
HEAD 対応、または middleware で HEAD→GET fallback。

---

## 次セッションが見るべき

1. plan `docs/superpowers/plans/2026-05-12-phase5-A-persistence-backend-plan.md`
   の現在地確認
2. failing 2 test を pass させる
3. 残タスク (RunIndex caching、CLI からのサーバ起動、OpenAPI / README) を
   plan の順序で消化
4. **オプション**: E (edit endpoints) の足場も同 spec 内にあるので、
   read-only 完了後に着手するかどうか判断

---

## なぜこのノートを切り出したか

本セッション (2026-05-13) で Piper portability 作業を
`feat/piper-portability` 別ブランチに切り出すことになり、その際にこの
WIP ファイルが untracked のまま残ることが判明。ブランチ切替や他セッションの
自動実行で WIP を踏みつぶさないよう、占有を明文化したのが本ノート。

実コード (`mimicanno/server/`, `tests/server/`) は作業者本人が別途 commit する
予定。Claude セッションからは触らない。
