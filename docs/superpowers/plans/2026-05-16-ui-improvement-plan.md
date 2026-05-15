# UI 改善 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** MimicAnno フロントエンドをニュートラルダークテーマに変更し、HandViewer を RunViewer 相当のレイアウト（サイドパネル + SVG スクラブバー）に統一する。

**Architecture:** App.css に CSS カスタムプロパティ（`--bg` 等）を追加して全体テーマを切り替え、新規 `HandScrubBar.tsx`（SVG クリック seek）を作成して HandViewer のレイアウトを左:動画+スクラブ / 右:データパネルに変更する。

**Tech Stack:** React 19, TypeScript, Vitest, @testing-library/react, SVG, CSS Custom Properties

Spec: `docs/superpowers/specs/2026-05-16-ui-improvement-design.md`

---

## §0 変更ファイル一覧

| ファイル | 変更内容 |
|---|---|
| `frontend/src/App.css` | CSS 変数追加 + 決め打ち値を変数参照に置き換え + HandViewer クラス新規定義 |
| `frontend/src/components/HandScrubBar.tsx` | 新規: SVG スクラブバーコンポーネント |
| `frontend/src/components/HandViewer.tsx` | レイアウト改修 (back-link / h1 削除 / HandScrubBar 追加 / ResizeObserver) |
| `frontend/src/components/__tests__/HandScrubBar.test.tsx` | 新規テスト |
| `frontend/src/components/__tests__/HandViewer.test.tsx` | テスト追加 |

---

## §1 出口基準

1. ブラウザで `?api=1` を開いたとき背景が `#171717` ダーク系になっている
2. HandViewer が サイドパネルレイアウト (左: 動画+スクラブバー / 右: データパネル) で表示される
3. `← runs` back-link が存在し `"/"` を指す。`h1` タイトルが消えている
4. スクラブバーをクリックするとフレームが移動する
5. 全テスト green (`pnpm test --run`)

---

## §2 タスク

### T1: App.css — CSS 変数 + テーマ変更 (1 commit)

**変更内容**:

1. `:root {}` ブロックを追加（spec §1 CSS カスタムプロパティをそのまま使用）
2. 既存の決め打ち値を変数参照に置き換え（下表）
3. HandViewer 用 CSS クラスを新規追加（下記）

**既存ルール変更:**

```css
/* before → after */
body { background: #fafafa; color: #111 }
  → body { background: var(--bg); color: var(--text) }

.run-list th, .run-list td { border-bottom: 1px solid #ddd }
  → border-bottom: 1px solid var(--border)

.run-list a { color: #1d4ed8 }
  → color: var(--link)

.error { color: #991b1b }
  → background: var(--error-bg); color: var(--error-text)
  (padding: 1rem は変更しない — M1 修正)

.chooser-banner { background: #fef3c7 }
  → background: var(--warn-bg); color: var(--text)

.pipeline-status-banner { background: #fee2e2 }
  → background: var(--degrade-bg); color: var(--text)

.waveform-label { color: #444 }  → color: var(--text-muted)
.waveform-unit  { color: #999 }  → color: var(--text-muted)
```

**HandViewer クラス新規追加（App.css 末尾に追記）:**

```css
/* HandViewer */
.hand-viewer { padding: 1rem; background: var(--bg); }
.hand-viewer-layout { display: flex; flex-direction: row; gap: 1rem; align-items: flex-start; }
.hand-viewer-video { flex: 3; min-width: 0; }
.hand-viewer-data { flex: 2; min-width: 0; background: var(--bg-surface); border-radius: 4px; }
.hand-data-panel { padding: 0.75rem; }
.hand-side { margin-bottom: 0.75rem; }
.hand-undetected { color: var(--text-muted); }
.hand-estimated { opacity: 0.4; }
.hand-badge { font-size: 11px; color: var(--text-muted); margin-left: 0.25rem; }
.hand-scrub-info { font-size: 11px; color: var(--text-muted); margin-top: 2px; }
```

テスト不要（CSS のみ。ブラウザで目視確認）。

Commit: `feat(ui): dark theme CSS variables + HandViewer CSS classes`

---

### T2: `HandScrubBar.tsx` 新規作成 + テスト (1 commit)

**`frontend/src/components/HandScrubBar.tsx`**:

```tsx
type Props = {
  widthPx: number;
  totalFrames: number;
  currentFrame: number;
  onSeek: (frame: number) => void;
};

export default function HandScrubBar({ widthPx, totalFrames, currentFrame, onSeek }: Props) {
  if (widthPx <= 0 || totalFrames <= 0) return null;

  const x = (currentFrame / totalFrames) * widthPx;

  function handleClick(e: React.MouseEvent<SVGSVGElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    const frame = Math.min(
      Math.round((clickX / widthPx) * totalFrames),
      totalFrames - 1,
    );
    onSeek(frame);
  }

  return (
    <svg
      width={widthPx}
      height={24}
      style={{ display: "block", background: "var(--bg-surface)", cursor: "pointer" }}
      onClick={handleClick}
    >
      <line x1={x} y1={0} x2={x} y2={24} stroke="#f1f5f9" strokeWidth={1.5} />
    </svg>
  );
}
```

**`frontend/src/components/__tests__/HandScrubBar.test.tsx`**:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import HandScrubBar from "../HandScrubBar";

describe("HandScrubBar", () => {
  it("returns null when widthPx=0", () => {
    const { container } = render(
      <HandScrubBar widthPx={0} totalFrames={100} currentFrame={0} onSeek={vi.fn()} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("returns null when totalFrames=0", () => {
    const { container } = render(
      <HandScrubBar widthPx={400} totalFrames={0} currentFrame={0} onSeek={vi.fn()} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("calls onSeek with correct frame on center click", () => {
    const onSeek = vi.fn();
    const { container } = render(
      <HandScrubBar widthPx={400} totalFrames={100} currentFrame={0} onSeek={onSeek} />,
    );
    const svg = container.querySelector("svg")!;
    // jsdom の getBoundingClientRect は left=0 を返すのでモック不要 (S4 修正)
    // ただし instance プロパティとして定義しておく (vitest が prototype spy を嫌う場合の保険)
    Object.defineProperty(svg, "getBoundingClientRect", {
      value: () => ({ left: 0, top: 0, right: 400, bottom: 24, width: 400, height: 24, x: 0, y: 0, toJSON: () => ({}) }),
    });
    fireEvent.click(svg, { clientX: 200 });
    expect(onSeek).toHaveBeenCalledWith(50);
  });

  it("renders playhead line at correct x position", () => {
    const { container } = render(
      <HandScrubBar widthPx={400} totalFrames={100} currentFrame={25} onSeek={vi.fn()} />,
    );
    const line = container.querySelector("line")!;
    expect(line.getAttribute("x1")).toBe("100");  // 25/100 * 400 = 100
  });
});
```

Run: `cd frontend && pnpm test --run src/components/__tests__/HandScrubBar.test.tsx`

Commit: `feat(ui): HandScrubBar SVG component + tests`

---

### T3: `HandViewer.tsx` レイアウト改修 (1 commit)

**変更内容:**

1. **`h1` 削除**: `<h1>hand viewer — {episodeId}</h1>` を削除

2. **back-link 変更**:
   ```tsx
   // before
   <a href="/">← 戻る</a>
   // after
   <div className="back-link">
     <a href="/">← runs</a>
   </div>
   ```
   `back-link` クラスは RunViewer と共通の App.css ルール（既存）を使う。

0. **import 追加** (M3 修正):
   ```tsx
   import HandScrubBar from "./HandScrubBar";
   ```

3. **ResizeObserver 追加**: `widthPx` state と `rowRef` callback を追加
   ```tsx
   const [widthPx, setWidthPx] = useState(0);
   const obsRef = useRef<ResizeObserver | null>(null);
   const rowRef = useCallback((node: HTMLDivElement | null) => {
     obsRef.current?.disconnect();
     obsRef.current = null;
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

4. **時刻フォーマット関数追加**:
   ```tsx
   function formatTime(sec: number): string {
     const mm = Math.floor(sec / 60).toString().padStart(2, "0");
     const ss = (sec % 60).toFixed(1).padStart(4, "0");
     return `${mm}:${ss}`;
   }
   ```

5. **JSX 変更** (loaded 状態のみ):
   ```tsx
   return (
     <div className="hand-viewer">
       <div className="back-link">
         <a href="/">← runs</a>
       </div>
       <div className="hand-viewer-layout">
         <div className="hand-viewer-video" ref={rowRef}>
           <VideoWithAxes ... />
           {videoError && <div className="error">{videoError}</div>}
           <HandScrubBar
             widthPx={widthPx}
             totalFrames={totalFrames}
             currentFrame={currentFrame}
             onSeek={(f) => fps > 0 && setCurrentTimeSec(f / fps)}
           />
           <div className="hand-scrub-info">
             frame {currentFrame} / {totalFrames - 1}{"  |  "}{formatTime(currentTimeSec)}
           </div>
         </div>
         <div className="hand-viewer-data">
           <HandDataPanel frameKey={frameKey} signals={signals} />
         </div>
       </div>
     </div>
   );
   ```

**`HandViewer.test.tsx` への追加テスト:**

```tsx
it("loaded state に SVG スクラブバーが存在する", async () => {
  render(<HandViewer episodeId="GX010085" />);
  await waitFor(() => expect(screen.queryByText(/loading/)).toBeNull());
  // widthPx=0 のため HandScrubBar は null を返す (jsdom で ResizeObserver 未発火)
  // SVG が null でも back-link と hand-scrub-info は存在する
  expect(screen.getByText(/frame 0 \/ 2/)).toBeTruthy();
});

it("back-link が '/' を指す", async () => {
  render(<HandViewer episodeId="GX010085" />);
  await waitFor(() => expect(screen.queryByText(/loading/)).toBeNull());
  const link = screen.getByText("← runs") as HTMLAnchorElement;
  expect(link.getAttribute("href")).toBe("/");
});

it("h1 タイトルが存在しない", async () => {
  render(<HandViewer episodeId="GX010085" />);
  await waitFor(() => expect(screen.queryByText(/loading/)).toBeNull());
  expect(document.querySelector("h1")).toBeNull();
});
```

> **M4 修正**: コロン除去に伴う既存テスト修正。`HandViewer.test.tsx` 全体を grep して `frame:` の regex を全件 `frame` に変更する:
> ```bash
> grep -n "frame:" frontend/src/components/__tests__/HandViewer.test.tsx
> ```
> 対象: `/frame: 0 \/ 2/` × 2件、`/frame: 2 \/ 2/` × 1件 → コロンなし版に修正。

**formatTime テスト追加 (S1 修正)**:
```tsx
it("scrub-info に時刻が表示される", async () => {
  render(<HandViewer episodeId="GX010085" />);
  await waitFor(() => expect(screen.queryByText(/loading/)).toBeNull());
  // frame 0, currentTimeSec=0 → "00:00.0"
  expect(screen.getByText(/00:00\.0/)).toBeTruthy();
});
```

Run: `cd frontend && pnpm test --run src/components/__tests__/HandViewer.test.tsx`

Commit: `feat(ui): HandViewer layout — back-link, HandScrubBar, resize observer`

---

### T4: 全テスト + ビルド確認 (修正があれば commit)

```bash
cd frontend && pnpm test --run 2>&1 | tail -20
cd frontend && pnpm build 2>&1 | tail -20
```

失敗があれば修正してから進む (N5 修正: pnpm build で TS エラーを拾う)。

---

## §3 smoke 確認項目

1. ブラウザで `/?api=1` 開く → 背景ダーク、テキスト明るい
2. episode を開く → `← runs` back-link が存在、`h1` なし
3. HandViewer (`?hand=GX010085&api=1`) → サイドパネルレイアウト、スクラブバー表示
4. スクラブバークリック → フレーム移動
5. `.error` / `.chooser-banner` / `.pipeline-status-banner` の視認性 OK

---

## §4 実装上の注意

- `back-link` CSS は App.css に **既に定義されていない** → T1 で追加する。`font-size: 14px` は RunViewer の back-link にも適用されるため **省く** (M2 修正。inherited サイズのまま):
  ```css
  .back-link { margin-bottom: 0.5rem; }
  .back-link a { color: var(--link); text-decoration: none; }
  .back-link a:hover { text-decoration: underline; }
  ```
- `.run-set-selector` / `.run-set-label` は run-set-switcher で追加されたが App.css に未定義。T1 に以下を追加する (S2 修正):
  ```css
  .run-set-selector { display: flex; gap: 0.5rem; align-items: center; margin-bottom: 0.5rem; }
  .run-set-selector select { background: var(--bg-surface); color: var(--text); border: 1px solid var(--border); padding: 2px 6px; }
  .run-set-label { color: var(--text-muted); font-size: 13px; margin-bottom: 0.5rem; }
  ```
- `hand-viewer-data` の `table` セルには `border-bottom: 1px solid var(--border)` が当たらないため、必要に応じて `.hand-data-panel table td` ルールを追加する
- `ResizeObserver` は jsdom で動作しないため、HandScrubBar テストでは `widthPx=0` (non-render) をメインパスとし、ブラウザ smoke でシーク動作を確認する
- `hand-scrub-info` のテキストが `frame: N / M` → `frame N / M` に変わるため既存テスト 2 件の regex を修正する
