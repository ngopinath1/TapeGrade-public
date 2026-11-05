import { Copy } from "lucide-react";
import type { Scan } from "../types";

export function Recommendation({
  scan,
  onToast,
}: {
  scan: Scan | null;
  onToast: (message: string) => void;
}) {
  const move = scan?.result?.staged_move;
  const copy = async () => {
    if (!move) return;
    try {
      await navigator.clipboard.writeText(
        `TapeGrade ${scan?.mode === "mock" ? "SIMULATED DEMO" : scan?.result?.league_is_demo === false ? "live Sleeper league report" : "live model report (sample league)"}\nADD ${move.add_player.name}\nDROP ${move.drop_player.name}\n${move.faab_bid === null ? "No FAAB bid applies" : `FAAB $${move.faab_bid}`}\n${move.reasoning}\nRecommendation only. Make any roster move in Sleeper.`,
      );
      onToast("Recommendation copied.");
    } catch {
      onToast("Clipboard unavailable in this browser.");
    }
  };
  return (
    <section className="recommendation" aria-labelledby="recommendation-title">
      <div className="section-heading">
        <h2 id="recommendation-title">
          {scan?.result?.film_test
            ? "Diagnostic result"
            : "Scan recommendation"}
        </h2>
        {move && <span className="recommendation-label">For your review</span>}
      </div>
      <p className="recommendation-scope">
        Best supported move across this scan. Your player selection changes the
        film view.
      </p>
      {move ? (
        <>
          <div className="move-summary">
            <div className="move-player">
              <span className="move-direction">Add</span>
              <div>
                <strong>{move.add_player.name}</strong>
                <small>
                  {move.add_player.team} ·{" "}
                  {move.add_player.positions.join(" / ")}
                </small>
              </div>
            </div>
            <div className="move-player drop">
              <span className="move-direction">Drop</span>
              <div>
                <strong>{move.drop_player.name}</strong>
                <small>
                  {move.drop_player.team} ·{" "}
                  {move.drop_player.positions.join(" / ")}
                </small>
              </div>
            </div>
            <div className="bid-row">
              <span>
                {move.faab_bid === null
                  ? "Acquisition"
                  : "Recommended FAAB bid"}
              </span>
              <strong>
                {move.faab_bid === null
                  ? "No bid applies"
                  : `$${move.faab_bid}`}
              </strong>
              {scan?.result?.league_is_demo !== false &&
                move.faab_bid !== null && <small>Sample FAAB</small>}
            </div>
          </div>
          <p className="move-reason">{move.reasoning}</p>
          <p className="move-instruction">
            Make this move in Sleeper after reviewing the film and current
            player availability.
          </p>
          <div className="recommendation-actions">
            <p className="awaiting">
              <strong>Review before you act.</strong>
              <span>Recommendation only</span>
            </p>
            <button className="button" onClick={copy}>
              <Copy size={15} /> Copy move summary
            </button>
          </div>
        </>
      ) : (
        <div className="move-empty">
          <h3>
            {scan?.result
              ? scan.result.film_test
                ? "Film review only"
                : "No recommended transaction"
              : "No recommendation yet"}
          </h3>
          <p>
            {scan?.result?.guardrail_notice ??
              (scan?.result
                ? scan.result.film_test
                  ? "This diagnostic checks tracking quality. It does not compare players or recommend a roster move."
                  : "No move cleared the film evidence and your guardrails. Review the player verdicts to see what was missing."
                : "A validated add, drop and bid will appear after your scan.")}
          </p>
        </div>
      )}
    </section>
  );
}
