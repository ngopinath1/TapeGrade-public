import { useState } from "react";
import { Loader2, Moon, Sun } from "lucide-react";
import type { Bootstrap, Guardrails } from "../types";
import { percent } from "../lib/api";
import type { Appearance } from "../hooks/useAppearance";

const scoringLabels: Record<string, string> = {
  pts: "Points",
  reb: "Rebounds",
  ast: "Assists",
  stl: "Steals",
  blk: "Blocks",
  to: "Turnovers",
  turnover: "Turnovers",
  tov: "Turnovers",
  tpm: "3-pointers made",
  tpa: "3-pointers attempted",
  fg3m: "3-pointers made",
  fg3a: "3-pointers attempted",
  fgm: "Field goals made",
  fga: "Field goals attempted",
  fgmi: "Field goals missed",
  ftm: "Free throws made",
  fta: "Free throws attempted",
  ftmi: "Free throws missed",
  tpmi: "3-pointers missed",
  oreb: "Offensive rebounds",
  dreb: "Defensive rebounds",
  pf: "Personal fouls",
  tf: "Technical fouls",
  ff: "Flagrant fouls",
  dd: "Double-doubles",
  td: "Triple-doubles",
  bonus_pt_40p: "40+ point bonus",
  bonus_pt_50p: "50+ point bonus",
};

export function Settings({
  data,
  onSave,
  appearance,
  onAppearance,
}: {
  data: Bootstrap;
  onSave: (settings: Guardrails) => Promise<void>;
  appearance: Appearance;
  onAppearance: (appearance: Appearance) => void;
}) {
  const [value, setValue] = useState(data.settings);
  const [saving, setSaving] = useState(false);
  const [scoringDraft, setScoringDraft] = useState<Record<string, string>>({});
  const weights = value.scoring_weights ?? data.league.scoring?.weights ?? {};
  const scoringKeys = [
    ...new Set([
      "pts",
      "reb",
      "ast",
      "stl",
      "blk",
      "to",
      ...Object.keys(weights),
    ]),
  ];
  const changed =
    JSON.stringify(value) !== JSON.stringify(data.settings) ||
    Object.entries(scoringDraft).some(
      ([key, draft]) =>
        draft !== String(data.league.scoring?.weights[key] ?? 0),
    );
  return (
    <section className="guardrails-panel settings-panel">
      <div className="settings-toolbar">
        <p className="page-description">
          Choose the limits your recommendations must respect.
        </p>
        <div>
          <span className="save-state" role="status">
            {changed ? "Unsaved changes" : "All changes saved"}
          </span>
          <button
            type="submit"
            form="guardrails-form"
            disabled={saving || !changed}
            className="button primary"
          >
            {saving && <Loader2 className="spin" size={15} />}
            {saving ? "Saving…" : "Save guardrails"}
          </button>
        </div>
      </div>
      <fieldset className="settings-section">
        <legend>Appearance</legend>
        <div className="settings-group">
          <div className="setting-row appearance-row">
            <span>
              Color mode
              <small>Applies immediately and remembers your choice.</small>
            </span>
            <div
              className="filter-group appearance-control"
              role="group"
              aria-label="Color mode"
            >
              {(
                [
                  { id: "light", label: "Light", icon: Sun },
                  { id: "dark", label: "Dark", icon: Moon },
                ] as const
              ).map((option) => (
                <button
                  key={option.id}
                  type="button"
                  aria-pressed={appearance === option.id}
                  onClick={() => onAppearance(option.id)}
                >
                  <option.icon size={15} aria-hidden="true" /> {option.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </fieldset>
      <form
        id="guardrails-form"
        onSubmit={async (event) => {
          event.preventDefault();
          setSaving(true);
          try {
            await onSave(value);
            setScoringDraft({});
          } catch {
            // The workspace displays the save error and retains these edits.
          } finally {
            setSaving(false);
          }
        }}
      >
        <fieldset className="settings-section">
          <legend>Recommendation limits</legend>
          <div className="settings-group">
            <label className="setting-row">
              <span>
                Minimum verdict confidence
                <small>
                  Required for an ADD recommendation. This is analysis
                  confidence, not a probability of future success.
                </small>
              </span>
              <span className="range-control">
                <input
                  type="range"
                  aria-label="Minimum verdict confidence"
                  min="0"
                  max="1"
                  step=".01"
                  value={value.min_confidence}
                  aria-valuetext={percent(value.min_confidence)}
                  onChange={(event) =>
                    setValue({
                      ...value,
                      min_confidence: Number(event.target.value),
                    })
                  }
                />
                <output>{percent(value.min_confidence)}</output>
              </span>
            </label>
            <label className="setting-row">
              <span>
                Maximum FAAB bid ($)
                <small>Also capped by your remaining league budget.</small>
              </span>
              <input
                type="number"
                min="0"
                max="1000"
                required
                value={value.max_faab_bid}
                onChange={(event) =>
                  setValue({
                    ...value,
                    max_faab_bid: Number(event.target.value),
                  })
                }
              />
            </label>
          </div>
        </fieldset>
        <fieldset className="settings-section">
          <legend>Fantasy scoring</legend>
          <p className="settings-description">
            Set fantasy points awarded per stat. Use negative values for
            penalties and 0 to ignore a stat.
            {data.league.is_demo === false &&
              " These local weights apply to recent game averages and new scans. Sleeper’s league settings and reported period totals are unchanged."}
            {
              " Changing scoring withdraws existing staged moves; run a new scan with your saved weights."
            }
          </p>
          <div className="settings-group scoring-grid">
            {scoringKeys.map((key) => (
              <label key={key} className="setting-row">
                <span>
                  {scoringLabels[key] ?? key.toUpperCase()}
                  <small>{key.toUpperCase()} · points per stat</small>
                </span>
                <input
                  type="number"
                  aria-label={`${scoringLabels[key] ?? key.toUpperCase()} scoring weight`}
                  min="-1000"
                  max="1000"
                  step="any"
                  required
                  value={scoringDraft[key] ?? weights[key] ?? 0}
                  onChange={(event) => {
                    const draft = event.target.value;
                    setScoringDraft({ ...scoringDraft, [key]: draft });
                    if (
                      draft !== "" &&
                      Number.isFinite(event.target.valueAsNumber)
                    ) {
                      setValue({
                        ...value,
                        scoring_weights: {
                          ...weights,
                          [key]: event.target.valueAsNumber,
                        },
                      });
                    }
                  }}
                />
              </label>
            ))}
          </div>
        </fieldset>
        <fieldset className="settings-section">
          <legend>
            Protected players{" "}
            <span className="section-count">
              {value.protected_players.length} selected
            </span>
          </legend>
          <p className="settings-description">
            Selected players will never be recommended as a drop. Others can be
            evaluated using{" "}
            {data.league.is_demo === false
              ? "current, verified game statistics"
              : "the fictional sample statistics"}
            .
          </p>
          <div className="settings-group protected-list">
            {data.league.roster.map((player) => (
              <label key={player.id} className="setting-row check-label">
                <span>
                  {player.name}
                  <small>
                    {player.team} · {player.positions.join(" / ")}
                  </small>
                </span>
                <input
                  type="checkbox"
                  checked={value.protected_players.includes(player.id)}
                  onChange={(event) =>
                    setValue({
                      ...value,
                      protected_players: event.target.checked
                        ? [...value.protected_players, player.id]
                        : value.protected_players.filter(
                            (id) => id !== player.id,
                          ),
                    })
                  }
                />
              </label>
            ))}
          </div>
        </fieldset>
        <fieldset className="settings-section">
          <legend>Scheduled scouting</legend>
          <div className="settings-group">
            <label className="setting-row check-label">
              <span>
                Nightly scan<small>1:30 AM · Eastern time</small>
              </span>
              <input
                type="checkbox"
                checked={value.schedule_enabled}
                disabled={!data.scheduler_available}
                onChange={(event) =>
                  setValue({ ...value, schedule_enabled: event.target.checked })
                }
              />
            </label>
            <label className="setting-row">
              <span>
                Additional pre-waiver scan<small>Eastern time</small>
              </span>
              <select
                aria-label="Additional pre-waiver scan (Eastern)"
                value={value.pre_waiver_hour ?? ""}
                disabled={!data.scheduler_available}
                onChange={(event) =>
                  setValue({
                    ...value,
                    pre_waiver_hour:
                      event.target.value === ""
                        ? null
                        : Number(event.target.value),
                  })
                }
              >
                <option value="">Off</option>
                {Array.from({ length: 24 }, (_, index) => (
                  <option key={index} value={index}>
                    {String(index).padStart(2, "0")}:00
                  </option>
                ))}
              </select>
            </label>
          </div>
          <p className="settings-description">
            {data.scheduler_available
              ? "Available while this Mac is awake and TapeGrade’s worker is running. Recommendations still need your review."
              : "Scheduled scans are unavailable in this environment. Run a manual scan from the scouting desk."}
          </p>
        </fieldset>
        <details className="mode-settings">
          <summary>Model environment & scan limits</summary>
          <p>
            Models:{" "}
            <b>
              {data.models_mode === "mock"
                ? "Simulated demo"
                : "Live Meta models"}
            </b>{" "}
            · League:{" "}
            <b>
              {data.league.is_demo === false
                ? "Sleeper NBA"
                : "Fictional NBA sample"}
            </b>
          </p>
          <p>
            {data.limits.candidates} candidates · up to {data.limits.retries}{" "}
            SAM retries · {data.limits.live_calls} live calls per scan
          </p>
          <p>
            Credentials stay on the backend. Change MOCK_MODELS and restart the
            API and worker to switch environments. Enable SCHEDULER_ENABLED to
            activate scheduling.
          </p>
        </details>
      </form>
    </section>
  );
}
