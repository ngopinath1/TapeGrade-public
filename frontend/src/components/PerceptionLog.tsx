import { Activity, Target, Sparkles } from "lucide-react";
import type { Candidate, Scan } from "../types";
import { percent } from "../lib/api";

export function PerceptionLog({
  scan,
  selected,
}: {
  scan: Scan | null;
  selected?: Candidate;
}) {
  const events = (scan?.events ?? []).filter((e) =>
    ["TRACKING", "CRITIQUING", "SWITCHING_CLIPS", "FAILED"].includes(e.stage),
  );
  return (
    <section className="panel perception-panel">
      <div className="panel-head">
        <div className="section-label">Tracking audit</div>
        <span className="tag">
          <span className="live-dot" />{" "}
          {scan?.mode === "live" ? "Actual operations" : "Simulated example"}
        </span>
      </div>
      <div className="log-intro">
        <h2>How the tracking was checked</h2>
        <p>
          Tracking attempts, quality checks, and any corrections made during
          this scan.
        </p>
      </div>
      {events.length ? (
        <div className="log-list">
          {events.map((e, i) => (
            <div className="log-row" key={e.id}>
              <span
                className={`log-node ${e.message.includes("insufficient") ? "warning" : ""}`}
              >
                {e.actor === "SAM 3.1" ? (
                  <Target size={12} />
                ) : (
                  <Sparkles size={12} />
                )}
              </span>
              <div>
                <span className="log-actor">
                  {e.actor}{" "}
                  <small>
                    {e.stage === "TRACKING" ? "PERCEPTION" : "REASONING"}
                  </small>
                </span>
                <p>{e.message}</p>
                {typeof e.detail.prompt === "string" && (
                  <code>“{e.detail.prompt}”</code>
                )}
              </div>
              <span className="log-index">
                {String(i + 1).padStart(2, "0")}
              </span>
            </div>
          ))}
        </div>
      ) : (
        <div className="log-idle">
          <Activity size={24} />
          <p>
            The full tracking and critique audit trail will appear during your
            scan.
          </p>
        </div>
      )}
      {selected && (
        <div className="quality-row">
          <span>Selected player · final perception quality</span>
          <b>{percent(selected.quality)}</b>
          <div>
            <i style={{ width: percent(selected.quality) }} />
          </div>
        </div>
      )}
      {selected?.critiques.length ? (
        <details className="method-note">
          <summary>Saved critic assessments</summary>
          {selected.critiques.map((critique) => (
            <p key={critique.attempt}>
              <b>
                {critique.clip_attempt
                  ? `Clip ${critique.clip_attempt} · Pass ${critique.tracking_attempt ?? 1}`
                  : `Attempt ${critique.attempt + 1}`}{" "}
                · {percent(critique.quality_score)}:
              </b>{" "}
              {critique.explanation}{" "}
              {critique.retry_justified
                ? "Retry requested by critic."
                : "No retry requested by critic."}
            </p>
          ))}
        </details>
      ) : null}
    </section>
  );
}
