import { useRef, useState } from "react";
import {
  X,
  Loader2,
  Search,
  Check,
  ExternalLink,
  ArrowRight,
} from "lucide-react";
import { api } from "../lib/api";
import { useDialogFocus } from "../hooks/useDialogFocus";

export function SleeperDialog({
  close,
  onConnected,
  connection,
}: {
  close: () => void;
  onConnected: () => Promise<void>;
  connection?: { username: string; league_id: string };
}) {
  const dialog = useRef<HTMLElement>(null);
  useDialogFocus(true, dialog, close, "input");
  const [username, setUsername] = useState(connection?.username ?? ""),
    [leagueId, setLeagueId] = useState(connection?.league_id ?? ""),
    [result, setResult] = useState<Record<string, unknown> | null>(null),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(false);
  const [leagueDetail, setLeagueDetail] = useState<{
    league: { name: string };
    rosters: unknown[];
    users: unknown[];
    source: string;
  } | null>(null);
  return (
    <div className="modal-backdrop" onClick={close}>
      <section
        ref={dialog}
        className="modal panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="sleeper-title"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          className="icon-button modal-close"
          onClick={close}
          aria-label="Close league connection"
        >
          <X size={20} />
        </button>
        <div className="section-label">League connection</div>
        <h2 id="sleeper-title">Connect your Sleeper league.</h2>
        <p>
          Enter your username and NBA league ID. TapeGrade imports your roster
          and scoring settings, then refreshes them when you run a scan. No
          Sleeper password is needed.
        </p>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            setLoading(true);
            setError("");
            try {
              const response = await api<Record<string, unknown>>(
                "/sleeper/connect",
                {
                  method: "POST",
                  body: JSON.stringify({
                    username,
                    ...(leagueId ? { league_id: leagueId } : {}),
                  }),
                },
              );
              setResult(response);
              if (response.connected) {
                await onConnected();
                close();
              }
            } catch (err) {
              setError((err as Error).message);
            } finally {
              setLoading(false);
            }
          }}
        >
          <label>
            Sleeper username
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              placeholder="your_username"
            />
          </label>
          <label>
            NBA league ID
            <input
              value={leagueId}
              onChange={(e) => setLeagueId(e.target.value.trim())}
              inputMode="numeric"
              required
              pattern="[0-9]{1,30}"
              maxLength={30}
              placeholder="From your Sleeper league URL"
            />
          </label>
          <button className="button primary" disabled={loading}>
            {loading ? (
              <Loader2 size={16} className="spin" />
            ) : (
              <Search size={16} />
            )}
            {connection ? "Refresh league" : "Connect NBA league"}
          </button>
        </form>
        {error && (
          <p className="inline-error" role="alert">
            {error}
          </p>
        )}
        {result && (
          <div className="connection-result">
            <Check size={18} />
            <strong>
              {String(
                (result.user as Record<string, unknown>)?.display_name ??
                  username,
              )}
            </strong>
            <p>{String(result.notice)}</p>
            {Array.isArray(result.leagues) && (
              <label>
                Documented NFL leagues
                <select
                  defaultValue=""
                  onChange={async (e) => {
                    setLeagueDetail(null);
                    if (!e.target.value) return;
                    setError("");
                    try {
                      setLeagueDetail(
                        await api(`/sleeper/leagues/${e.target.value}`),
                      );
                    } catch (err) {
                      setError((err as Error).message);
                    }
                  }}
                >
                  <option value="">Select a league (view only)</option>
                  {(result.leagues as Record<string, unknown>[]).map((l) => (
                    <option
                      key={String(l.league_id)}
                      value={String(l.league_id)}
                    >
                      {String(l.name)}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {leagueDetail && (
              <div className="league-readout">
                <strong>{leagueDetail.league.name}</strong>
                <p>
                  {leagueDetail.rosters.length} rosters ·{" "}
                  {leagueDetail.users.length} managers
                </p>
                <small>
                  {leagueDetail.source}. NFL view only; basketball scouting uses
                  the sample league.
                </small>
              </div>
            )}
          </div>
        )}
        <details className="connection-details">
          <summary>About NBA league connections</summary>
          <p>
            NBA access is verified by league ID. Automatic league discovery is
            documented for NFL only. TapeGrade reads league data and never
            submits roster moves.
          </p>
          <a
            className="text-link"
            href="https://docs.sleeper.com/#get-all-leagues-for-user"
            target="_blank"
            rel="noreferrer"
          >
            Read Sleeper API limitations <ExternalLink size={12} />
          </a>
        </details>
        <button
          className="button subtle full"
          onClick={async () => {
            try {
              await api("/workspace/demo", { method: "POST" });
              await onConnected();
              close();
            } catch (err) {
              setError((err as Error).message);
            }
          }}
        >
          Continue with the sample NBA league <ArrowRight size={15} />
        </button>
      </section>
    </div>
  );
}
