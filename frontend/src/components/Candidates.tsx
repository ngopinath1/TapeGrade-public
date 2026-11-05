import { Bookmark } from "lucide-react";
import type { Candidate } from "../types";
import { percent } from "../lib/api";
import { VerdictBadge } from "./Player";

export function Candidates({
  candidates,
  selected,
  onSelect,
  watchlist,
  onWatch,
  emptyReason,
}: {
  candidates: Candidate[];
  selected: string;
  onSelect: (id: string) => void;
  watchlist: string[];
  onWatch: (id: string) => void;
  emptyReason?: string;
}) {
  return (
    <section className="candidates-panel" aria-label="Scouted candidates">
      <div className="candidate-heading">
        <h2>Players</h2>
        <span>{candidates.length}</span>
      </div>
      {candidates.length ? (
        <div className="candidate-list">
          {candidates.map((candidate, index) => (
            <div
              className={`candidate ${selected === candidate.player.id ? "selected" : ""}`}
              key={candidate.player.id}
            >
              <button
                className="candidate-main"
                onClick={() => onSelect(candidate.player.id)}
                aria-pressed={selected === candidate.player.id}
                aria-label={`Rank ${index + 1} ${candidate.player.name} ${candidate.player.team} ${candidate.verdict.verdict}`}
              >
                <span className="candidate-name">
                  <strong>{candidate.player.name}</strong>
                  <small>
                    {candidate.player.team} ·{" "}
                    {candidate.player.positions.join(" / ")}
                  </small>
                </span>
                <VerdictBadge value={candidate.verdict.verdict} />
                <span className="candidate-stats">
                  {candidate.player.film_only
                    ? "Film test · stats unavailable"
                    : candidate.player.is_demo === false
                      ? `${candidate.player.recent_fantasy_average ?? "—"} FPTS/game · n=${candidate.player.recent?.sample_size ?? 0}`
                      : `${candidate.player.fantasy_points} FPTS`}
                  <span>
                    {percent(candidate.verdict.confidence)} confidence
                  </span>
                </span>
              </button>
              <button
                className={`icon-button watch ${watchlist.includes(candidate.player.id) ? "watched" : ""}`}
                aria-label={`${watchlist.includes(candidate.player.id) ? "Remove" : "Add"} ${candidate.player.name} ${watchlist.includes(candidate.player.id) ? "from" : "to"} watchlist`}
                aria-pressed={watchlist.includes(candidate.player.id)}
                onClick={() => onWatch(candidate.player.id)}
              >
                <Bookmark size={15} />
              </button>
            </div>
          ))}
        </div>
      ) : (
        <div className="board-empty">
          <h3>No candidates in this report</h3>
          <p>
            {emptyReason ??
              "Try a broader request or another position. Review the scan details for any missing evidence."}
          </p>
        </div>
      )}
      <p className="candidate-footnote">
        Ranked by role, opportunity, and film evidence.
      </p>
    </section>
  );
}
