import { useState } from "react";
import { LockKeyhole, Search, X } from "lucide-react";
import type { Bootstrap } from "../types";
import { Sparkline } from "./Player";
import { InfoTooltip } from "./InfoTooltip";

export function Roster({
  data,
  onManageProtections,
}: {
  data: Bootstrap;
  onManageProtections?: () => void;
}) {
  const [query, setQuery] = useState("");
  const [protectedOnly, setProtectedOnly] = useState(false);
  const players = data.league.roster.filter(
    (p) =>
      (!protectedOnly || data.settings.protected_players.includes(p.id)) &&
      `${p.name} ${p.team} ${p.positions.join(" ")}`
        .toLowerCase()
        .includes(query.toLowerCase().trim()),
  );
  const live = data.league.is_demo === false;
  return (
    <section className="roster-panel">
      <div className="panel-head">
        <h2 className="roster-team-name">{data.league.team_name}</h2>
        <span className="tag">
          {live
            ? `Sleeper · period ${data.league.period ?? "—"}`
            : "Fictional sample roster"}
        </span>
      </div>
      {!live && (
        <p className="roster-overview">
          {data.league.record} · {data.league.standing} ·{" "}
          {data.league.faab_remaining === null
            ? "Budget unavailable"
            : `$${data.league.faab_remaining} remaining`}{" "}
          · {data.settings.protected_players.length} protected players
        </p>
      )}
      {live && (
        <div className="sleeper-roster-summary">
          <div>
            <span className="section-label">
              {data.league.name} · {data.league.season}
            </span>
            <h2>
              {data.league.period_points ?? "—"} <small>team points</small>
            </h2>
            <p>
              {data.league.roster.length} players · Sleeper-reported scoring
              period {data.league.period ?? "unavailable"}. These are period
              totals, not averages.
            </p>
          </div>
          <span className="tag">READ ONLY · NBA COMPATIBILITY</span>
        </div>
      )}
      <div className="roster-toolbar">
        <label className="search-field">
          <Search size={18} />
          <span className="sr-only">Search roster</span>
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search name, team, or position"
          />
        </label>
        <div className="filter-group" role="group" aria-label="Roster filter">
          <button
            aria-pressed={!protectedOnly}
            onClick={() => setProtectedOnly(false)}
          >
            All players
          </button>
          <button
            aria-pressed={protectedOnly}
            onClick={() => setProtectedOnly(true)}
          >
            Protected
          </button>
        </div>
        <InfoTooltip label="roster filters">
          All players shows your full roster. Protected shows only players you
          have marked as never-drop in Guardrails. Search works within either
          view.
        </InfoTooltip>
        {onManageProtections && (
          <button className="button subtle" onClick={onManageProtections}>
            Manage protections
          </button>
        )}
      </div>
      <p className="roster-count" role="status">
        {players.length} of {data.league.roster.length} players
      </p>
      <div
        className="table-scroll"
        role="region"
        aria-label="Roster table"
        tabIndex={0}
      >
        <table>
          <caption className="sr-only">
            {data.league.team_name} player statistics and protection status
          </caption>
          <thead>
            <tr>
              <th scope="col">
                <span className="column-heading">
                  Player{" "}
                  <InfoTooltip label="player">
                    The player’s name and NBA team on your current roster.
                  </InfoTooltip>
                </span>
              </th>
              <th scope="col">
                <span className="column-heading">
                  Position{" "}
                  <InfoTooltip label="position">
                    The lineup positions this player is eligible to fill in your
                    league.
                  </InfoTooltip>
                </span>
              </th>
              <th scope="col">
                <span className="column-heading">
                  Min / prev{" "}
                  <InfoTooltip label="minutes and previous minutes">
                    {live
                      ? "Average minutes played in the recent game sample, followed by the average from the five earlier games. A dash means there is not enough recorded data."
                      : "Current and previous average minutes from the fictional sample. A higher current value suggests a growing role."}
                  </InfoTooltip>
                </span>
              </th>
              <th scope="col">
                <span className="column-heading">
                  {live ? `PERIOD ${data.league.period ?? "—"} FPTS` : "FPTS"}{" "}
                  <InfoTooltip label="fantasy points">
                    {live
                      ? "Fantasy points reported by Sleeper for this scoring period. This is a period total. Local scoring edits in Guardrails apply to recent game averages and future analysis; Sleeper’s reported totals stay as reported."
                      : "Fantasy points calculated from the fictional sample statistics using your scoring weights in Guardrails."}
                  </InfoTooltip>
                </span>
              </th>
              {live && (
                <th scope="col">
                  <span className="column-heading">
                    RECENT FPTS / GAME{" "}
                    <InfoTooltip label="recent fantasy points per game">
                      Average fantasy points per played game, using your
                      Guardrails scoring weights and up to five recent recorded
                      games. The game count (previously n) is the sample size
                      used for this average. Recorded DNPs are excluded; missing
                      data can make the average unavailable.
                    </InfoTooltip>
                  </span>
                </th>
              )}
              <th scope="col">
                <span className="column-heading">
                  {live ? "Recent FPTS trend" : "7-game FPTS trend"}{" "}
                  <InfoTooltip label="fantasy points trend">
                    {live
                      ? "Each point shows one game’s fantasy points from the recent sample, from oldest on the left to newest on the right. Higher means more fantasy points. Each player has their own vertical scale, so compare the shape within a row. At least two scored games are needed."
                      : "Each point shows fictional fantasy points for one of seven sample games, oldest on the left and newest on the right. Each player has their own vertical scale. Custom scoring hides this trend because the sample has no per-game box scores to recalculate it."}
                  </InfoTooltip>
                </span>
              </th>
              <th scope="col">
                <span className="column-heading">
                  Status{" "}
                  <InfoTooltip label="player status">
                    Protected players cannot be recommended as a drop. Other
                    players show their lineup or injury status when available.
                    Manage protections in Guardrails.
                  </InfoTooltip>
                </span>
              </th>
            </tr>
          </thead>
          <tbody>
            {players.map((p) => (
              <tr key={p.id}>
                <td>
                  <div className="table-player">
                    <span>
                      <b>{p.name}</b>
                      <small>{p.team}</small>
                    </span>
                  </div>
                </td>
                <td>{p.positions.join(" / ")}</td>
                <td>
                  {p.minutes ?? "—"}{" "}
                  <span className="muted">/ {p.previous_minutes ?? "—"}</span>
                </td>
                <td className="numeric">{p.fantasy_points ?? "—"}</td>
                {live && (
                  <td className="numeric" title={p.recent?.reasons.join(" ")}>
                    {p.recent_fantasy_average ?? "—"}
                    <small className="muted">
                      {p.recent
                        ? ` · ${p.recent.sample_size} ${p.recent.sample_size === 1 ? "game" : "games"}`
                        : " · no game logs"}
                    </small>
                  </td>
                )}
                <td>
                  <Sparkline
                    values={p.trend}
                    label={`${p.name}: fantasy points, oldest to newest: ${p.trend.join(", ")}`}
                    muted={p.trend.at(-1)! < p.trend[0]}
                  />
                </td>
                <td>
                  {data.settings.protected_players.includes(p.id) ? (
                    <span className="protected">
                      <LockKeyhole size={12} /> Protected
                    </span>
                  ) : (
                    <span className="muted">
                      {p.lineup_status ?? "Flexible"}
                      {p.injury_status ? ` · ${p.injury_status}` : ""}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!players.length && (
        <div className="board-empty">
          <Search size={28} />
          <h3>No players match</h3>
          <p>Try another name, team, or position.</p>
          <button
            className="button subtle"
            onClick={() => {
              setQuery("");
              setProtectedOnly(false);
            }}
          >
            <X size={15} /> Clear filters
          </button>
        </div>
      )}
      <p className="data-note">{data.league.notice}</p>
      <p className="data-note">
        <b>Your scoring weights:</b>{" "}
        {Object.entries(data.league.scoring?.weights ?? {})
          .map(([key, value]) => `${key.toUpperCase()} × ${value}`)
          .join(" · ")}
        {" · Edit in Guardrails."}
      </p>
      {live && (
        <>
          {data.league.points_warning && (
            <p className="data-note">
              Points unavailable: {data.league.points_warning}
            </p>
          )}
          <p className="data-note">
            Saved{" "}
            {data.league.fetched_at
              ? new Date(data.league.fetched_at).toLocaleString()
              : "locally"}
            . Refresh through Connect Sleeper. Player names are cached for 24
            hours; league reads for up to five minutes.
          </p>
        </>
      )}
    </section>
  );
}
