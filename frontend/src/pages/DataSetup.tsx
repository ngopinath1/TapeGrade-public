import { useEffect, useRef, useState, type ReactNode } from "react";
import { RefreshCw, Upload } from "lucide-react";
import type { Bootstrap } from "../types";
import { api } from "../lib/api";
import { ScanReadiness } from "../components/ScanReadiness";
import type { SetupSection } from "../components/ScoutingGuide";
import { SectionTabs } from "../components/SectionTabs";

type Proposal = {
  sleeper_id: string;
  name: string;
  status: string;
  matches: { id: string; name: string; team: string | null }[];
};
type Status = {
  provider: string;
  provider_configured: boolean;
  window_days?: number;
  request_limit?: number;
  summary: {
    provider: string;
    start_date: string;
    end_date: string;
    fetched_at: string;
    synthetic: boolean;
  } | null;
  jobs: {
    id: string;
    status: string;
    error: string | null;
    identity_review: Proposal[];
  }[];
};

export function DataSetup({
  data,
  onRefresh,
  onError,
  initialSection,
  onDone,
}: {
  data: Bootstrap;
  initialSection?: SetupSection;
  onDone?: () => void;
  onRefresh: () => Promise<void>;
  onError: (message: string) => void;
}) {
  const sectionId = (value?: SetupSection) =>
    value === "statistics"
      ? "overview"
      : value === "coverage"
        ? "logs"
        : (value ?? "overview");
  const [section, setSection] = useState(sectionId(initialSection));
  useEffect(() => {
    setSection(sectionId(initialSection));
  }, [initialSection]);
  const importInput = useRef<HTMLInputElement>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState("");
  const [mappingQuery, setMappingQuery] = useState("");
  const [mappingSource, setMappingSource] = useState("");
  const [source, setSource] = useState(data.league.rules?.source_ref ?? "");
  const [mode, setMode] = useState(data.league.rules?.game_mode ?? "unknown");
  const [waivers, setWaivers] = useState(
    data.league.rules?.waiver_mode ?? "unknown",
  );
  const [bonuses, setBonuses] = useState(
    data.league.rules?.point_bonus_mode ?? "unknown",
  );
  const [faabBudget, setFaabBudget] = useState<number | "">(
    data.league.rules?.faab_budget ??
      (typeof data.league.rule_settings?.waiver_budget === "number"
        ? data.league.rule_settings.waiver_budget
        : ""),
  );
  const [message, setMessage] = useState("");
  const [eligibilityPlayer, setEligibilityPlayer] = useState("");
  const [acquisition, setAcquisition] = useState("unknown");
  const [dropAllowed, setDropAllowed] = useState(false);
  const [eligibilitySource, setEligibilitySource] = useState("");
  const players = [...data.league.roster, ...data.league.available];
  const load = async () => setStatus(await api<Status>("/stats"));
  useEffect(() => {
    void load().catch((e) => onError(e.message));
  }, [data.league.id]);
  const running = status?.jobs.some((j) =>
    ["QUEUED", "RUNNING"].includes(j.status),
  );
  useEffect(() => {
    if (!running) return;
    const timer = setTimeout(async () => {
      try {
        await load();
        await onRefresh();
      } catch (e) {
        onError((e as Error).message);
      }
    }, 1500);
    return () => clearTimeout(timer);
  }, [status, running]);
  const act = async (task: () => Promise<unknown>, success: string) => {
    setBusy(true);
    setMessage("");
    onError("");
    try {
      await task();
      await load();
      await onRefresh();
      setMessage(success);
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const proposals =
    status?.jobs.find((j) => j.status === "COMPLETED")?.identity_review ?? [];
  const filtered = players.filter((p) =>
    p.name.toLowerCase().includes(query.toLowerCase()),
  );
  const panels: Record<string, ReactNode> = {
    overview: (
      <section className="panel settings-panel">
        <div className="panel-head">
          <h2>League data</h2>
          <span className="tag">
            {data.league.scouting_ready ? "Statistics ready" : "Setup required"}
          </span>
        </div>
        <p className="muted">
          Recent averages use up to five completed games in the same declared
          window ({status?.window_days ?? 30} days for new refreshes), with at
          least three observations. Period totals remain separate. Missing foul
          counts prevent exact scoring.
        </p>
        <ul className="data-note">
          {data.league.readiness_reasons?.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
        <p className="data-note">
          {data.league.stats_coverage
            ? `${data.league.stats_coverage.ready_candidates} supported candidates · ${data.league.stats_coverage.ready_drops} supported unprotected drops`
            : "No complete game-log snapshot yet."}
        </p>
        {status?.summary && (
          <p className="data-note">
            {status.summary.synthetic
              ? "SYNTHETIC FIXTURE"
              : status.summary.provider}{" "}
            · {status.summary.start_date} to {status.summary.end_date} · fetched{" "}
            {new Date(status.summary.fetched_at).toLocaleString()}
          </p>
        )}
        <div className="data-actions">
          <button
            className="button subtle"
            disabled={busy}
            onClick={() =>
              void act(
                () => api("/sleeper/refresh", { method: "POST" }),
                "Sleeper roster and rules refreshed. Game logs are refreshed separately; waiver status and drop locks still need review in Eligibility.",
              )
            }
          >
            <RefreshCw size={15} /> Refresh Sleeper roster
          </button>
          <button
            className="button primary"
            disabled={busy || running}
            onClick={() =>
              void act(
                () => api("/stats/refresh", { method: "POST" }),
                "Game-log refresh queued. You can keep using TapeGrade while it updates.",
              )
            }
          >
            <RefreshCw size={15} /> Refresh game logs
          </button>
          <button
            type="button"
            className="button subtle"
            disabled={busy || running}
            onClick={() => importInput.current?.click()}
          >
            <Upload size={15} /> Import licensed JSON
          </button>
          <input
            ref={importInput}
            aria-label="Licensed game-log JSON"
            type="file"
            accept=".json,application/json"
            hidden
            disabled={busy || running}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (!file) return;
              e.target.value = "";
              if (file.size > 20 * 1024 * 1024) {
                onError("Game-log imports must be under 20 MB.");
                return;
              }
              void act(
                async () =>
                  api("/stats/import", {
                    method: "POST",
                    body: JSON.stringify(JSON.parse(await file.text())),
                  }),
                "Import queued for validation.",
              );
            }}
          />
        </div>
        <p className="data-note">
          Game logs update basketball statistics. Refresh Sleeper roster updates
          league membership and rules. Neither confirms a player’s current
          waiver state or Lock-In drop eligibility.
        </p>
        <ScanReadiness data={data} />
        <p className="data-note">
          Source: {status?.provider ?? "loading"} ·{" "}
          {status?.provider_configured
            ? "Key configured on backend"
            : "No provider key configured"}
          . Import format:{" "}
          <a href="http://localhost:8000/docs" target="_blank" rel="noreferrer">
            StatsBatch in API explorer
          </a>
          . Imports require provenance and explicit synthetic labeling.
        </p>
        {status?.jobs.slice(0, 3).map((j) => (
          <p className="data-note" key={j.id}>
            {j.status} · {j.id.slice(0, 8)} {j.error && `· ${j.error}`}
          </p>
        ))}
      </section>
    ),
    rules: (
      <section className="panel settings-panel">
        <div className="panel-head">
          <h2>League rules</h2>
        </div>
        <p className="muted">
          Check Sleeper’s league settings and a scored 50-point game before
          saving bonus behavior. Numeric API codes remain uninterpreted. Save
          optional protected players in Guardrails. Everyone else can be
          evaluated using current, verified statistics.
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void act(
              () =>
                api("/league/rules", {
                  method: "PUT",
                  body: JSON.stringify({
                    game_mode: mode,
                    waiver_mode: waivers,
                    point_bonus_mode: bonuses,
                    faab_budget:
                      waivers === "faab" && faabBudget !== ""
                        ? faabBudget
                        : null,
                    source_ref: source,
                  }),
                }),
              "Rule evidence saved.",
            );
          }}
        >
          <div className="settings-grid">
            {waivers === "faab" && (
              <label>
                FAAB season budget ($)
                <input
                  type="number"
                  min={0}
                  max={10000}
                  value={faabBudget}
                  onChange={(e) =>
                    setFaabBudget(
                      e.target.value === "" ? "" : Number(e.target.value),
                    )
                  }
                />
              </label>
            )}
            <label>
              Basketball mode
              <select value={mode} onChange={(e) => setMode(e.target.value)}>
                <option value="unknown">Unverified</option>
                <option value="lock_in">Lock-In</option>
                <option value="game_pick">Game Pick</option>
              </select>
            </label>
            <label>
              Waiver mode
              <select
                value={waivers}
                onChange={(e) => setWaivers(e.target.value)}
              >
                <option value="unknown">Unverified</option>
                <option value="faab">FAAB waivers</option>
                <option value="priority">Priority waivers</option>
                <option value="free_agent">Free agency only</option>
              </select>
            </label>
            <label>
              40/50-point bonuses
              <select
                value={bonuses}
                onChange={(e) => setBonuses(e.target.value)}
              >
                <option value="unknown">Unverified</option>
                <option value="stack">Both bonuses stack at 50+</option>
                <option value="highest_only">Highest threshold only</option>
              </select>
            </label>
            <label>
              Verification source
              <input
                value={source}
                onChange={(e) => setSource(e.target.value)}
                minLength={10}
                maxLength={1000}
                required
                placeholder="Settings checked and scored-game reference"
              />
            </label>
          </div>
          <p className="data-note">
            One game per week counts in Lock-In and Game Pick. Recent per-game
            averages are comparisons, not weekly projections. Current raw codes:
            game_mode=
            {String(data.league.rule_settings?.game_mode ?? "unknown")},
            waiver_type=
            {String(data.league.rule_settings?.waiver_type ?? "unknown")}.
          </p>
          <button className="button primary" disabled={busy}>
            Save verified rule evidence
          </button>
        </form>
      </section>
    ),
    identity: (
      <section className="panel settings-panel">
        <div className="panel-head">
          <h2>Player identities</h2>
        </div>
        <p className="muted">
          Exact normalized names are proposals. Review each athlete using
          independent evidence before linking; transfers can change teams.
        </p>
        <label>
          Identity verification source
          <input
            required
            minLength={10}
            maxLength={1000}
            value={mappingSource}
            onChange={(e) => setMappingSource(e.target.value)}
            placeholder="Independent player identity evidence"
          />
        </label>
        <input
          aria-label="Search identity proposals"
          placeholder="Find a player to verify"
          value={mappingQuery}
          onChange={(e) => setMappingQuery(e.target.value)}
        />
        {proposals
          .filter(
            (p) =>
              p.status !== "verified" &&
              p.name.toLowerCase().includes(mappingQuery.toLowerCase()),
          )
          .slice(0, 12)
          .map((p) => (
            <div className="identity-row" key={p.sleeper_id}>
              <div>
                <b>{p.name}</b>
                <small>
                  {" "}
                  · {p.status} · Sleeper {p.sleeper_id}
                </small>
              </div>
              {p.matches.map((m) => (
                <button
                  className="button subtle"
                  disabled={busy || mappingSource.length < 10}
                  key={m.id}
                  onClick={() =>
                    void act(
                      () =>
                        api("/stats/mappings", {
                          method: "POST",
                          body: JSON.stringify({
                            sleeper_id: p.sleeper_id,
                            athlete_id: m.id,
                            source_ref: mappingSource,
                          }),
                        }),
                      "Identity reviewed and linked.",
                    )
                  }
                >
                  Confirm {m.name} · {m.team ?? "team unknown"} · ID {m.id}
                </button>
              ))}
            </div>
          ))}
        {!proposals.some((p) => p.status !== "verified") && (
          <p className="data-note">
            No unresolved player matches. Import or refresh game logs to check
            for new matches.
          </p>
        )}
      </section>
    ),
    eligibility: (
      <section className="panel settings-panel">
        <div className="panel-head">
          <h2>Transaction eligibility</h2>
        </div>
        <p className="muted">
          Unrostered status does not prove addability. Check the candidate’s
          waiver state and the proposed drop’s locks in Sleeper. This evidence
          is needed for add/drop recommendations; you can run a scouting report
          without it.
        </p>
        <ol className="data-note">
          <li>Refresh the Sleeper roster in Overview.</li>
          <li>
            Choose a free agent below, select “Immediate free agent” or “On
            waivers” based on Sleeper, and save your verification source.
          </li>
          <li>
            Choose a rostered player with supported recent scores, confirm that
            Sleeper allows dropping them with no Lock-In lock, and save again.
          </li>
          <li>
            Run the scan within five minutes. The candidate needs an uploaded
            clip in Film library, and the roster after the swap must fit your
            league’s position slots.
          </li>
        </ol>
        <p className="data-note">
          Eligible players are never inferred from unrostered status. Manual
          eligibility evidence expires after five minutes.
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void act(
              () =>
                api("/league/eligibility", {
                  method: "PUT",
                  body: JSON.stringify({
                    player_id: eligibilityPlayer,
                    acquisition,
                    drop_allowed: dropAllowed,
                    source_ref: eligibilitySource,
                  }),
                }),
              "Eligibility evidence saved for five minutes.",
            );
          }}
        >
          <div className="settings-grid">
            <label>
              Player
              <select
                required
                value={eligibilityPlayer}
                onChange={(e) => {
                  setEligibilityPlayer(e.target.value);
                  setAcquisition("unknown");
                  setDropAllowed(false);
                }}
              >
                <option value="">Choose player</option>
                {players.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} ·{" "}
                    {data.league.roster.some((r) => r.id === p.id)
                      ? "roster"
                      : "unrostered"}
                    {p.recent?.ready
                      ? " · recent scores ready"
                      : " · statistics incomplete"}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Acquisition status
              <select
                value={acquisition}
                onChange={(e) => setAcquisition(e.target.value)}
              >
                <option value="unknown">Unknown / rostered</option>
                <option value="free_agent">Immediate free agent</option>
                <option value="waivers">On waivers</option>
                <option value="locked">Locked</option>
              </select>
            </label>
            <label className="check-label">
              <input
                type="checkbox"
                checked={dropAllowed}
                onChange={(e) => setDropAllowed(e.target.checked)}
              />
              Drop allowed; no Lock-In or other lock
            </label>
            <label>
              Current verification source
              <input
                required
                minLength={10}
                maxLength={1000}
                value={eligibilitySource}
                onChange={(e) => setEligibilitySource(e.target.value)}
                placeholder="Sleeper player and lineup state checked"
              />
            </label>
          </div>
          <button
            className="button primary"
            disabled={busy || !eligibilityPlayer}
          >
            Save eligibility evidence
          </button>
        </form>
      </section>
    ),
    logs: (
      <section className="panel settings-panel">
        <div className="panel-head">
          <h2>Game logs</h2>
        </div>
        <input
          aria-label="Search recent game logs"
          placeholder="Search all players"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <p className="data-note">
          Showing {Math.min(30, filtered.length)} of {filtered.length} matches.
          Search to find any player. FAAB is shown only when applicable to a
          verified waiver claim.
        </p>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>PLAYER</th>
                <th>PERIOD TOTAL</th>
                <th>RECENT FPTS / GAME</th>
                <th>MINUTES</th>
                <th>EVIDENCE</th>
              </tr>
            </thead>
            <tbody>
              {filtered.slice(0, 30).map((p) => (
                <tr key={p.id}>
                  <td>
                    <b>{p.name}</b>
                    <small> · {p.team}</small>
                  </td>
                  <td>
                    {data.league.roster.some((r) => r.id === p.id)
                      ? (p.fantasy_points ?? "—")
                      : "—"}
                  </td>
                  <td>
                    {p.recent_fantasy_average ?? "—"} · n=
                    {p.recent?.sample_size ?? 0}
                  </td>
                  <td>
                    {p.minutes ?? "—"} / {p.previous_minutes ?? "—"}
                  </td>
                  <td>
                    <button
                      className="text-link"
                      onClick={() => setExpanded(expanded === p.id ? "" : p.id)}
                    >
                      {p.recent?.ready ? "View sourced games" : "View gaps"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {expanded &&
          (() => {
            const p = players.find((p) => p.id === expanded);
            return (
              <div className="game-details">
                <h3>{p?.name}</h3>
                <p className="data-note">
                  {p?.recent?.provider ?? "No statistics source"} ·{" "}
                  {p?.recent?.window_start} to {p?.recent?.window_end}
                </p>
                {p?.recent && (
                  <p className="data-note">
                    Recorded DNPs: {p.recent.recorded_dnp_count ?? 0} · Unknown
                    participation: {p.recent.unknown_participation_count ?? 0}.
                    These do not count as played games.
                  </p>
                )}
                {p?.recent?.reasons.map((r) => (
                  <p className="data-note" key={r}>
                    {r}
                  </p>
                ))}
                {!p?.recent && (
                  <p className="data-note">No complete game-log snapshot.</p>
                )}
                {p?.recent?.games.map((g) => (
                  <p className="data-note" key={g.row_id}>
                    {g.date} · {g.minutes ?? "unknown"} min ·{" "}
                    {g.score ?? "unavailable"} FPTS · {g.source_ref}
                    <br />
                    Observed fields: {g.coverage.join(", ")}
                  </p>
                ))}
              </div>
            );
          })()}
      </section>
    ),
  };
  return (
    <div className="data-setup">
      {onDone && (
        <button className="text-link" onClick={onDone}>
          Back to scouting
        </button>
      )}
      <p className="page-description">
        Set up the evidence your scouting reports rely on.
      </p>
      {message && (
        <p role="status" className="setup-feedback">
          {message}
        </p>
      )}
      <SectionTabs
        label="League setup sections"
        selected={section}
        onSelect={setSection}
        tabs={[
          { id: "overview", label: "Overview" },
          { id: "rules", label: "Rules" },
          { id: "identity", label: "Player identities" },
          { id: "eligibility", label: "Eligibility" },
          { id: "logs", label: "Game logs" },
        ]}
      >
        {(id) => panels[id]}
      </SectionTabs>
    </div>
  );
}
