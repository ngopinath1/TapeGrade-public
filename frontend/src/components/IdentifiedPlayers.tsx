import { ExternalLink, Users } from "lucide-react";
import type { ObservedPlayerProfile } from "../types";

const availability = {
  available: "Unrostered in your league",
  your_roster: "On your roster",
  rostered_elsewhere: "On another team's roster",
  unknown: "League availability unconfirmed",
};
const verdicts: Record<string, string> = {
  ADD: "Consider adding",
  MONITOR: "Monitor",
  PASS: "Pass",
  MORE_DATA: "More data needed",
  TRADE_RESEARCH: "Trade research",
  READY_FOR_REVIEW: "Ready for comparison",
};
function sourceLink(source: string) {
  if (
    source.startsWith("cache:stats/") &&
    /^cache:stats\/[a-z0-9_/-]+\.json$/.test(source)
  )
    return "/media/cache/" + source.slice(6);
  return source.startsWith("https://") ? source : null;
}

export function IdentifiedPlayers({
  profiles,
}: {
  profiles?: ObservedPlayerProfile[];
}) {
  if (!profiles?.length) return null;
  return (
    <section
      className="observed-players"
      aria-label="Identified player performance"
    >
      <div className="observed-heading">
        <Users size={17} />
        <h3>Players in this clip</h3>
        <span>{profiles.length} roster matches</span>
      </div>
      <p>
        Each player's jersey links to the game roster and their own recent
        statistics. Fantasy points use your league's scoring.
      </p>
      <div className="observed-grid">
        {profiles.map((p) => (
          <article
            key={p.id}
            className="observed-card"
            aria-label={`${p.name} performance`}
          >
            <div className="observed-player-heading">
              <div>
                <h4>{p.name}</h4>
                <p>
                  {p.team} #{p.jersey_number} · Track {p.object_id}
                </p>
              </div>
              <span className="tag">
                {verdicts[p.recommendation.verdict] ?? p.recommendation.verdict}
              </span>
            </div>
            <p className="observed-availability">
              {availability[p.availability]}
            </p>
            {p.statistics ? (
              <>
                <div className="observed-statline">
                  <div>
                    <strong>{p.statistics.fantasy_per_game ?? "—"}</strong>
                    <span>Fantasy pts/game</span>
                  </div>
                  <div>
                    <strong>{p.statistics.minutes_per_game ?? "—"}</strong>
                    <span>Minutes/game</span>
                  </div>
                  <div>
                    <strong>{p.statistics.sample_size}</strong>
                    <span>Completed games</span>
                  </div>
                </div>
                <dl className="observed-boxline">
                  {[
                    ["pts", "PTS"],
                    ["reb", "REB"],
                    ["ast", "AST"],
                    ["stl", "STL"],
                    ["blk", "BLK"],
                    ["tpm", "3PM"],
                  ].map(([key, label]) => (
                    <div key={key}>
                      <dt>{label}</dt>
                      <dd
                        title={`${p.statistics!.averages[key]?.sample_size ?? 0} observed games`}
                      >
                        {p.statistics!.averages[key]?.value ?? "—"}
                      </dd>
                    </div>
                  ))}
                </dl>
                <p className="observed-source">
                  {p.statistics.synthetic
                    ? "Synthetic fixture"
                    : p.statistics.provider}{" "}
                  · {p.statistics.window_start}–{p.statistics.window_end}
                  {!p.statistics.fresh ? " · Stale data" : ""}
                </p>
                {!p.statistics.ready && (
                  <ul className="observed-issues">
                    {p.statistics.reasons.map((reason) => (
                      <li key={reason}>{reason}</li>
                    ))}
                  </ul>
                )}
              </>
            ) : (
              <p className="verification-note">
                A unique statistics match could not be verified. No numbers were
                inferred from this player's name.
              </p>
            )}
            <p className="observed-film-state">
              {p.film.accepted
                ? "Film measurements available"
                : p.film.identity_continuity_confirmed
                  ? "Tracking needs review"
                  : "Player continuity not confirmed"}
            </p>
            <p className="observed-rationale">{p.recommendation.rationale}</p>
            <small>
              {p.recommendation.source === "model_with_guardrails"
                ? "Final report verdict"
                : "Evidence screening · final comparison still required"}
            </small>
            <details className="method-note">
              <summary>Game logs and identity sources</summary>
              {p.roster_source?.startsWith("https://") && (
                <a
                  className="text-link"
                  href={p.roster_source}
                  target="_blank"
                  rel="noreferrer"
                >
                  Game roster · {p.game_date}
                  <ExternalLink size={12} />
                </a>
              )}
              <p>
                Matched full name, team, jersey number and appearance in the
                dated game. Each tracking ID is checked separately before film
                measurements qualify.
              </p>
              {p.statistics && (
                <div className="observed-table-wrap">
                  <table>
                    <caption>Recent games for {p.name}</caption>
                    <thead>
                      <tr>
                        <th>Date</th>
                        <th>MIN</th>
                        <th>PTS</th>
                        <th>REB</th>
                        <th>AST</th>
                        <th>Fantasy</th>
                      </tr>
                    </thead>
                    <tbody>
                      {p.statistics.games.map((g) => (
                        <tr key={g.date}>
                          <td>
                            {sourceLink(g.source_ref) ? (
                              <a
                                href={sourceLink(g.source_ref)!}
                                target="_blank"
                                rel="noreferrer"
                                aria-label={`${p.name} source box score ${g.date}`}
                              >
                                {g.date}
                              </a>
                            ) : (
                              g.date
                            )}
                          </td>
                          <td>
                            {g.minutes === null
                              ? "—"
                              : Math.round(g.minutes * 10) / 10}
                          </td>
                          <td>{g.stats.pts ?? "—"}</td>
                          <td>{g.stats.reb ?? "—"}</td>
                          <td>{g.stats.ast ?? "—"}</td>
                          <td>{g.score ?? "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <p>
                    Statistics retrieved{" "}
                    {new Date(p.statistics.fetched_at).toLocaleString()}.
                  </p>
                </div>
              )}
            </details>
          </article>
        ))}
      </div>
    </section>
  );
}
