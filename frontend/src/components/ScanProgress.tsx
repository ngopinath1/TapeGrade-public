import { Check, Loader2 } from "lucide-react";
import type { Scan } from "../types";

const phases = [
  {
    label: "Refresh league",
    stages: ["QUEUED", "SYNCING_LEAGUE"],
    explanation: "Refreshing your Sleeper roster and available players.",
  },
  {
    label: "Update scores",
    stages: ["UPDATING_STATISTICS"],
    explanation: "Updating recent game logs. This can take a few minutes.",
  },
  {
    label: "Find players",
    stages: ["SCOUTING"],
    explanation: "Comparing available players with your team’s needs.",
  },
  {
    label: "Find footage",
    stages: ["FINDING_CLIPS"],
    explanation:
      "Finding matching permitted footage and recent player highlights.",
  },
  {
    label: "Check film",
    stages: [
      "VERIFYING",
      "TRACKING",
      "CRITIQUING",
      "SWITCHING_CLIPS",
      "CALCULATING_METRICS",
    ],
    explanation:
      "Checking player identity, tracking and the reliability of the film evidence.",
  },
  {
    label: "Build report",
    stages: ["DECIDING", "GENERATING_CARD"],
    explanation: "Comparing the evidence with your roster and saved limits.",
  },
];

export function ScanProgress({ scan }: { scan: Scan | null }) {
  const active = Math.max(
    0,
    phases.findIndex((p) => p.stages.includes(scan?.stage ?? "QUEUED")),
  );
  const progress = scan?.progress ?? 0;
  const switchEvent = scan?.events
    ?.filter((e) => e.stage === "SWITCHING_CLIPS")
    .at(-1);
  const switching = scan?.stage === "SWITCHING_CLIPS";
  return (
    <section className="scan-status panel" role="status" aria-live="polite">
      <div className="scan-status-heading">
        <Loader2 size={20} className="spin" />
        <div>
          <h2>
            {switching && switchEvent
              ? switchEvent.message
              : phases[active].explanation}
          </h2>
          <p>
            {switchEvent && active === 4 && !switching
              ? switchEvent.message
              : "You can visit other pages. Your report will be saved in Scan history."}
          </p>
        </div>
        <strong>{progress}%</strong>
      </div>
      <div
        className="scan-progress"
        role="progressbar"
        aria-label="Scouting progress"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={progress}
      >
        <i style={{ width: `${progress}%` }} />
      </div>
      <ol className="scan-phases">
        {phases.map((phase, index) => (
          <li
            key={phase.label}
            aria-current={index === active ? "step" : undefined}
          >
            {index < active ? <Check size={15} /> : <span>{index + 1}</span>}
            {phase.label}
          </li>
        ))}
      </ol>
    </section>
  );
}
