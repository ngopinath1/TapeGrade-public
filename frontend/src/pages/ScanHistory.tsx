import { useState } from "react";
import { ChevronRight, Search } from "lucide-react";
import type { Scan } from "../types";
import { complete } from "../lib/api";

export function ScanHistory({
  scans,
  onOpen,
  onStart,
}: {
  scans: Scan[];
  onOpen: (scan: Scan) => void;
  onStart: () => void;
}) {
  const [query, setQuery] = useState("");
  const matches = scans.filter((scan) =>
    scan.instruction.toLowerCase().includes(query.toLowerCase().trim()),
  );
  return (
    <section className="history-panel">
      <div className="collection-toolbar">
        <p>
          {scans.length} saved {scans.length === 1 ? "scan" : "scans"}
        </p>
        {scans.length > 0 && (
          <label className="search-field">
            <Search size={16} />
            <span className="sr-only">Search scan history</span>
            <input
              type="search"
              placeholder="Search scans"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
        )}
      </div>
      {matches.length ? (
        <div className="history-list">
          {matches.map((scan) => (
            <button
              key={scan.id}
              className="history-row"
              onClick={() => onOpen(scan)}
            >
              <span className="history-description">
                <strong>{scan.instruction}</strong>
                <small>
                  {new Date(scan.created_at).toLocaleString()} ·{" "}
                  {scan.mode === "mock" ? "Demo models" : "Live models"} ·
                  Attempt {scan.attempts} · {scan.live_calls} live calls
                </small>
              </span>
              <span
                className={`history-stage ${scan.stage === "FAILED" ? "failed" : ""}`}
              >
                {complete(scan.stage) && !scan.reviewed && (
                  <span className="unreviewed-label">Unreviewed · </span>
                )}
                {scan.stage.replaceAll("_", " ").toLowerCase()}
              </span>
              <ChevronRight size={16} />
            </button>
          ))}
        </div>
      ) : (
        <div className="board-empty">
          <h2>{scans.length ? "No matching scans" : "No scans yet"}</h2>
          <p>
            {scans.length
              ? "Try a different scouting mission."
              : "Your reports will be saved here so you can return to the evidence."}
          </p>
          {!scans.length && (
            <button className="button primary" onClick={onStart}>
              Start scouting
            </button>
          )}
        </div>
      )}
    </section>
  );
}
