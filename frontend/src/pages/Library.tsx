import { useState, useEffect } from "react";
import { Loader2 } from "lucide-react";
import type { Bootstrap, Clip } from "../types";
import { api } from "../lib/api";

export function Library({
  data,
  onError,
  onToast,
  onRefresh,
  onDone,
}: {
  data: Bootstrap;
  onError: (error: string) => void;
  onToast: (message: string) => void;
  onRefresh?: () => Promise<void>;
  onDone?: () => void;
}) {
  const [clips, setClips] = useState<Clip[]>([]);
  const [uploading, setUploading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [filename, setFilename] = useState("");
  const [query, setQuery] = useState("");
  const [playerId, setPlayerId] = useState("");
  const [saved, setSaved] = useState(false);
  const automatic = data.workflow?.public_footage_analysis_enabled === true;
  const available = data.league.available.filter(
    (player) => data.league.is_demo !== false || player.recent?.ready,
  );
  const matches = available.filter(
    (player) =>
      player.id === playerId ||
      player.name.toLowerCase().includes(query.toLowerCase()),
  );
  const refresh = async () => {
    const next = await api<Clip[]>("/clips");
    setClips(next);
  };
  useEffect(() => {
    void refresh()
      .catch((error) => onError(error.message))
      .finally(() => setLoading(false));
  }, []);
  const savedClips = clips.length > 0 && (
    <div className="clip-grid">
      {clips.map((clip) => (
        <article key={clip.id}>
          <video
            src={clip.url}
            controls
            preload="metadata"
            aria-label={`Clip of ${clip.subject_name ?? data.league.available.find((player) => player.id === clip.player_id)?.name ?? clip.player_id}`}
          />
          <div className="clip-info">
            <h2>
              {clip.subject_name ??
                data.league.available.find(
                  (player) => player.id === clip.player_id,
                )?.name ??
                clip.player_id}
            </h2>
            <span>{clip.duration.toFixed(1)}s</span>
            <p>
              {clip.source}
              {clip.game_date ? ` · Game date: ${clip.game_date}` : ""}
            </p>
            {clip.source_ref?.startsWith("https://") && (
              <a
                className="text-link"
                href={clip.source_ref}
                target="_blank"
                rel="noreferrer"
              >
                {clip.source_title ?? "View original source"}
              </a>
            )}
          </div>
        </article>
      ))}
    </div>
  );
  return (
    <section className="library-panel">
      <div className="collection-toolbar">
        <p>
          {loading
            ? "Loading your library…"
            : clips.length
              ? `${clips.length} ${clips.length === 1 ? "clip" : "clips"} available for scouting`
              : "No clips in your library"}
        </p>
        {clips.length > 0 && !adding && (
          <button className="button primary" onClick={() => setAdding(true)}>
            Add footage
          </button>
        )}
      </div>
      {automatic && (
        <p className="page-description">
          Scans find recent player-specific ESPN clips and save short excerpts
          here. Source dates and attribution stay attached; identity and
          tracking are checked during analysis.
        </p>
      )}
      {data.models_mode === "mock" && (
        <p className="data-note">
          The sample scan already includes film. Uploaded footage can be stored
          here, but simulated models cannot verify it.
        </p>
      )}
      {saved && (
        <div className="setup-feedback" role="status">
          <p>Clip saved. Return to scouting to check readiness.</p>
          <p>
            Player identity and tracking quality will be checked during the next
            live scan.
          </p>
          {onDone && (
            <button className="button" onClick={onDone}>
              Back to scouting
            </button>
          )}
        </div>
      )}
      {automatic && savedClips}
      {(!clips.length || adding || automatic) && (
        <details
          className={`manual-upload ${automatic ? "optional" : ""}`}
          open={!automatic || adding}
          onToggle={(event) => {
            if (automatic) setAdding(event.currentTarget.open);
          }}
        >
          <summary>Add your own clip (optional)</summary>
          <section className="upload-section" aria-labelledby="upload-title">
            <div className="section-heading">
              <h2 id="upload-title">Add footage</h2>
              {clips.length > 0 && (
                <button
                  className="text-link"
                  disabled={uploading}
                  onClick={() => setAdding(false)}
                >
                  Cancel
                </button>
              )}
            </div>
            <p className="page-description">
              Choose the player in your clip and upload footage you have
              permission to analyze.
            </p>
            <form
              className="upload-form"
              onSubmit={async (event) => {
                event.preventDefault();
                const formElement = event.currentTarget;
                setUploading(true);
                setSaved(false);
                onError("");
                try {
                  const form = new FormData(formElement);
                  form.set("rights_confirmed", "true");
                  await api("/clips", { method: "POST", body: form });
                  await refresh();
                  await onRefresh?.();
                  formElement.reset();
                  setFilename("");
                  setPlayerId("");
                  setQuery("");
                  setAdding(false);
                  setSaved(true);
                  onToast(
                    "Clip saved. Return to scouting to review readiness.",
                  );
                } catch (error) {
                  onError((error as Error).message);
                } finally {
                  setUploading(false);
                }
              }}
            >
              <div className="settings-group">
                <label className="upload-row">
                  <span>Find a player</span>
                  <input
                    type="search"
                    value={query}
                    disabled={uploading}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="Search free agents by name"
                  />
                </label>
                <label className="upload-row">
                  <span>Target player</span>
                  <select
                    name="player_id"
                    disabled={uploading}
                    required
                    value={playerId}
                    onChange={(event) => setPlayerId(event.target.value)}
                  >
                    <option value="">Choose player</option>
                    {matches.map((player) => (
                      <option key={player.id} value={player.id}>
                        {player.name} ·{" "}
                        {player.is_demo
                          ? "fictional demo player"
                          : "Sleeper player"}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="upload-row file-row">
                  <span>
                    Video file<small>MP4 or MOV · up to 100 MB</small>
                  </span>
                  <input
                    type="file"
                    name="file"
                    aria-label="Video file"
                    accept=".mp4,.mov"
                    required
                    disabled={uploading}
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      if (file && file.size > 100 * 1024 * 1024) {
                        event.target.value = "";
                        setFilename("");
                        onError("Choose a video under 100 MB.");
                      } else {
                        setFilename(file?.name ?? "");
                        onError("");
                      }
                    }}
                  />
                </label>
              </div>
              {data.league.is_demo === false && (
                <p className="data-note">
                  Showing {matches.length} free agents with comparable recent
                  scores. Prepare players without sufficient statistics in
                  League setup first.
                </p>
              )}
              {filename && <p className="selected-file">{filename}</p>}
              <p className="data-note">
                The first {data.limits.clip_seconds ?? 30} seconds are
                normalized and analyzed. Live mode sends the clip and selected
                frames to Meta. The visible player must match the target; mock
                models cannot verify real footage, and sample-league players are
                fictional.
              </p>
              <label className="check-label rights-confirmation">
                <input type="checkbox" required disabled={uploading} />
                <span>
                  I have the rights and consent needed to process this footage.
                </span>
              </label>
              <div className="form-actions">
                <button
                  className="button primary"
                  disabled={uploading || !playerId}
                >
                  {uploading && <Loader2 size={16} className="spin" />}
                  {uploading ? "Processing video…" : "Process local clip"}
                </button>
              </div>
            </form>
          </section>
        </details>
      )}
      {!automatic && savedClips}
    </section>
  );
}
