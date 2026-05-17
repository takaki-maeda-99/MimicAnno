import RunList from "./components/RunList";
import RunViewer from "./components/RunViewer";
import HandViewer from "./components/HandViewer";
import DatasetsPage from "./pages/DatasetsPage";
import JobsPage from "./pages/JobsPage";
import { ApiToggleProvider } from "./lib/ApiToggleContext";

export default function App() {
  const params = new URLSearchParams(window.location.search);
  const episodeId = params.get("run");
  const handEpisodeId = params.get("hand");
  const runHashShort = params.get("hash") ?? undefined;
  const apiEnabled = params.get("api") === "1";
  // S-RS: ?run_set= selects a subdirectory under the runs root.
  const runSet = params.get("run_set") ?? undefined;
  // U-A1: ?page= selects top-level pages (datasets | jobs).
  // Existing ?run= / ?hand= take priority over ?page= to preserve
  // backward compatibility with bookmarked viewer URLs.
  const page = params.get("page");

  const inner =
    handEpisodeId !== null ? (
      <HandViewer episodeId={handEpisodeId} />
    ) : episodeId !== null ? (
      <RunViewer episodeId={episodeId} runHashShort={runHashShort} runSet={runSet} />
    ) : page === "datasets" ? (
      <DatasetsPage />
    ) : page === "jobs" ? (
      <JobsPage />
    ) : (
      <RunList runSet={runSet} />
    );
  return <ApiToggleProvider apiEnabled={apiEnabled}>{inner}</ApiToggleProvider>;
}
