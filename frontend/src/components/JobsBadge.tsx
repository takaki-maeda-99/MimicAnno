/**
 * U-A5 — Site-wide progress badge.
 * Polls GET /api/jobs?status=running every 4 s.
 * Shows "N running" pill linking to ?page=jobs when N > 0; renders nothing otherwise.
 */
import { useEffect, useState } from "react";
import { fetchRunningCount } from "../lib/jobsBadgeClient";

const POLL_INTERVAL_MS = 4000;

export default function JobsBadge() {
  const [count, setCount] = useState<number>(0);

  useEffect(() => {
    let cancelled = false;

    const poll = () => {
      fetchRunningCount().then((n) => {
        if (!cancelled) setCount(n);
      });
    };

    poll();
    const interval = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  if (count === 0) return null;

  return (
    <a
      data-testid="jobs-badge"
      href="?page=jobs"
      style={{
        display: "inline-block",
        background: "#0d6efd",
        color: "white",
        padding: "3px 10px",
        borderRadius: 12,
        fontSize: "0.85em",
        textDecoration: "none",
        fontWeight: 600,
      }}
    >
      {count} running
    </a>
  );
}
