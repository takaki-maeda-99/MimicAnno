import RunList from "./components/RunList";
import RunViewer from "./components/RunViewer";
import { ApiToggleProvider } from "./lib/ApiToggleContext";

export default function App() {
  const params = new URLSearchParams(window.location.search);
  const episodeId = params.get("run");
  const runHashShort = params.get("hash") ?? undefined;
  // Phase 5 B r1 T12: ?api=1 switches fetches from static /runs/ to the
  // FastAPI /api/runs/ backend (and gates the editable phase dropdown
  // shipped in T13).
  const apiEnabled = params.get("api") === "1";

  const inner =
    episodeId === null ? (
      <RunList />
    ) : (
      <RunViewer episodeId={episodeId} runHashShort={runHashShort} />
    );
  return <ApiToggleProvider apiEnabled={apiEnabled}>{inner}</ApiToggleProvider>;
}
