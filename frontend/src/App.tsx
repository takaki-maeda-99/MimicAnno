import RunList from "./components/RunList";
import RunViewer from "./components/RunViewer";

export default function App() {
  const params = new URLSearchParams(window.location.search);
  const episodeId = params.get("run");
  const runHashShort = params.get("hash") ?? undefined;

  if (episodeId === null) {
    return <RunList />;
  }
  return <RunViewer episodeId={episodeId} runHashShort={runHashShort} />;
}
