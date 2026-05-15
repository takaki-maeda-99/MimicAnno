# UI 改善 — デザイン仕様 (2026-05-16)

## 概要

MimicAnno フロントエンドに 2 つの UI 改善を行う。

1. **全体テーマをニュートラルダークに変更** — `#fafafa` 白背景から `#171717` ダーク背景へ
2. **HandViewer を RunViewer 相当の GUI に統一** — サイドパネルレイアウト + カスタム SVG スクラブバー

どちらもフロントエンドのみの変更。バックエンド API の変更はなし。

---

## 1. テーマ変更

### 変更ファイル

- `frontend/src/App.css` のみ

### CSS カスタムプロパティ

`:root` に以下の変数を追加し、全ファイル内の決め打ち値を変数参照に置き換える。

```css
:root {
  --bg:          #171717;   /* ページ背景 */
  --bg-surface:  #262626;   /* カード・テーブル行背景 */
  --bg-elevated: #404040;   /* hover・セパレータ */
  --text:        #e5e5e5;   /* 本文テキスト */
  --text-muted:  #737373;   /* サブテキスト・ラベル */
  --border:      #404040;   /* テーブル罫線・区切り */
  --link:        #60a5fa;   /* リンク色（blue-400） */
  --error-bg:    #450a0a;   /* .error 背景 */
  --error-text:  #fca5a5;   /* .error テキスト */
  --warn-bg:     #451a03;   /* .chooser-banner 背景 */
  --degrade-bg:  #3f1212;   /* .pipeline-status-banner 背景 */
}
```

### 置き換え対象（App.css）

| セレクタ | 変更前 | 変更後 |
|---|---|---|
| `body` | `background: #fafafa; color: #111` | `background: var(--bg); color: var(--text)` |
| `.run-list th, td` | `border-bottom: 1px solid #ddd` | `border-bottom: 1px solid var(--border)` |
| `.run-list a` | `color: #1d4ed8` | `color: var(--link)` |
| `.error` | `color: #991b1b` | `background: var(--error-bg); color: var(--error-text)` |
| `.chooser-banner` | `background: #fef3c7` | `background: var(--warn-bg); color: var(--text)` |
| `.pipeline-status-banner` | `background: #fee2e2` | `background: var(--degrade-bg); color: var(--text)` |
| `.waveform-label` | `color: #444` | `color: var(--text-muted)` |
| `.waveform-unit` | `color: #999` | `color: var(--text-muted)` |

### HandViewer CSS クラスの新規定義

`HandViewer.tsx` は既に `className` 文字列でクラス名を参照しているが、**これらのクラスは App.css に定義されていない**（インラインスタイルとして存在する部分もある）。今回 App.css に以下のクラスを**新規作成**し、HandViewer.tsx のインラインスタイルを対応する className 参照に置き換える。

- `.hand-viewer` — パディング・背景色（`var(--bg)`）
- `.hand-viewer-layout` — flex row レイアウト、gap（今回の新レイアウト定義）
- `.hand-viewer-video` — 左ペイン、`flex: 3`
- `.hand-viewer-data` — 右ペイン、`flex: 2`、背景 `var(--bg-surface)`
- `.hand-data-panel` — パディング
- `.hand-side` — 各手セクション、マージン
- `.hand-undetected` — 未検出ラベル色（`var(--text-muted)`）
- `.hand-estimated` — `depth_ok=false` グレーアウト（`opacity: 0.4`）
- `.hand-badge` — (推定) バッジスタイル（文字色 `var(--text-muted)`）
- `.hand-scrub-info` — フレーム番号・時刻表示行（`font-size: 11px; color: var(--text-muted)`）

### スコープ外

- ライトモード切り替えトグルは実装しない
- タイムラインの `PHASE_PALETTE` 色は変更しない（既にダーク背景と相性が良い）

---

## 2. HandViewer レイアウト改善

### 新規コンポーネント: `HandScrubBar.tsx`

`frontend/src/components/HandScrubBar.tsx` を新規作成する。

#### Props

```ts
type Props = {
  widthPx: number;       // 0 のとき null を返す
  totalFrames: number;
  currentFrame: number;
  onSeek: (frame: number) => void;
};
```

#### 仕様

- SVG ベース、height = 24px
- 背景: `var(--bg-surface)`、境界線なし
- プレイヘッド: 白線（`#f1f5f9`）、strokeWidth 1.5
- クリックでシーク: `onClick` でクリック位置 → フレーム番号変換
- ドラッグシークは実装しない（スコープ外）
- `widthPx === 0` または `totalFrames <= 0` のとき `null` を返す

#### フレーム計算

```ts
const frame = Math.min(
  Math.round((x / widthPx) * totalFrames),
  totalFrames - 1
);
```

### HandViewer のレイアウト変更

#### 変更前（現状）

```
[h1: hand viewer — ep_xxx]
[← 戻る]
.hand-viewer-layout (flex row)
  .hand-viewer-video
    VideoWithAxes (video + canvas)
    frame: N / M
  .hand-viewer-data
    HandDataPanel
```

#### 変更後

```
[← runs]  ← RunViewer と同じ back-link スタイル
.hand-viewer-layout (flex row, gap)
  .hand-viewer-video (flex:3)
    VideoWithAxes (video + canvas、controls 維持)
    HandScrubBar (widthPx 連動)
    .hand-scrub-info: "frame N / M  |  MM:SS.s"
  .hand-viewer-data (flex:2)
    HandDataPanel (内容・グレーアウト維持)
```

#### ResizeObserver パターン

`VideoWithAxes` 内部の `<video>` は `maxWidth: 100%` + `inline-block` ラッパーで描画されるため、`.hand-viewer-video`（コンテナ）の幅と実際のビデオ描画幅が一致しない場合がある。スクラブバーをビデオと同幅にするため、ResizeObserver は **`VideoWithAxes` のラッパー `<div>`（`wrapRef`）** ではなく `.hand-viewer-video` にアタッチし、`HandScrubBar` の `widthPx` は `maxWidth: 100%` で渡す。スクラブバー自体も `maxWidth: 100%` にするため、ビデオより広くなることはない。

```tsx
const rowRef = useCallback((node: HTMLDivElement | null) => {
  obsRef.current?.disconnect();
  obsRef.current = null;  // RunViewer と同様に null クリア
  if (node) {
    const obs = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width ?? 0;
      if (w > 0) setWidthPx(w);
    });
    obs.observe(node);
    obsRef.current = obs;
  }
}, []);
```

#### 時刻表示フォーマット

```ts
const totalSec = currentTimeSec;
const mm = Math.floor(totalSec / 60).toString().padStart(2, "0");
const ss = (totalSec % 60).toFixed(1).padStart(4, "0");
// → "frame 540 / 1799  |  00:18.0"
```

#### `h1` タグの削除 と back-link テキスト変更

- `<h1>hand viewer — {episodeId}</h1>` を削除する
- `<a href="/">← 戻る</a>` を `<a href="/" className="back-link">← runs</a>` に変更し、RunViewer と同じスタイル・テキストに統一する

---

## 3. テスト

### 新規: `HandScrubBar.test.tsx`

| テスト | 内容 |
|---|---|
| `widthPx=0` でレンダリングしない | `null` を返すこと |
| `totalFrames=0` でレンダリングしない | `null` を返すこと |
| クリックで `onSeek` が正しいフレームで呼ばれる | 中央クリック（x = widthPx/2）、`totalFrames=10` → `Math.round(0.5 * 10) = 5`、`totalFrames=5` → `Math.round(0.5 * 5) = 3`（Math.round は .5 を切り上げ） |
| プレイヘッドが正しい x 座標に描画される | `currentFrame / totalFrames * widthPx` |

### 既存: `HandViewer.test.tsx` への追加

| テスト | 内容 |
|---|---|
| `loaded` 状態でスクラブバーが存在する | SVG 要素の存在確認 |
| back-link が `"/"` を指す | `← runs` の `href` 確認 |
| `h1` タグが存在しない | `queryByRole('heading', { level: 1 })` が null を返すこと |
| back-link テキストが変更されている | `getByRole('link', { name: '← runs' })` が存在し `href="/"` であること |

### 変更なし

- `RunViewer.integration.test.tsx`、`SegmentTable.test.tsx`、`RunList.test.tsx` は変更対象外

---

## 4. 実装順序

1. App.css テーマ変更（CSS 変数追加 + 値置き換え）
2. HandViewer CSS クラス整理
3. `HandScrubBar.tsx` 新規作成 + 単体テスト
4. `HandViewer.tsx` レイアウト改修 + テスト追加
5. 全テスト実行（82 件 + 新規）

---

## 5. 非目標

- ダーク/ライト切り替えトグル
- Timeline.tsx の HandViewer への流用（セグメント・境界データがないため不適）
- VideoPlayer.tsx の HandViewer への流用（canvas overlay との統合が複雑なため）
- ドラッグシーク
