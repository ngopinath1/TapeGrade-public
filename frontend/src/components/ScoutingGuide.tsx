import { ArrowRight, Check, Circle } from "lucide-react";
import type { Bootstrap } from "../types";

export type SetupSection =
  "statistics" | "rules" | "identity" | "eligibility" | "coverage";
export type GuideDestination =
  "desk" | "roster" | "data" | "library" | "settings" | "connect";

export function ScoutingGuide({
  data,
  hasReport,
  onNavigate,
}: {
  data: Bootstrap;
  hasReport: boolean;
  onNavigate: (destination: GuideDestination, section?: SetupSection) => void;
}) {
  const real = data.league.is_demo === false;
  const status = data.scan_readiness;
  const simulated = data.models_mode === "mock";
  if (data.workflow?.automatic || (data.workflow && !real && !simulated)) {
    if (hasReport) return null;
    const workflow = data.workflow;
    return (
      <section className="scouting-guide" aria-labelledby="guide-title">
        <span className="section-label">
          {real ? "LIVE SCOUTING" : "START WITH YOUR LEAGUE"}
        </span>
        <h2 id="guide-title">
          {real
            ? workflow.can_start
              ? "Your league is connected. Run a scan."
              : "One connection needs attention."
            : "Connect your league. The scout takes it from there."}
        </h2>
        <p>
          {real
            ? "Each scan refreshes your roster, updates recent scores, finds matching footage and checks the evidence before building your report."
            : "Connect Sleeper once. TapeGrade refreshes your league and searches for player footage when you scan."}
        </p>
        {!real && (
          <button
            className="button primary"
            onClick={() => onNavigate("connect")}
          >
            Connect your league
            <ArrowRight size={15} />
          </button>
        )}
        {real && workflow.blockers.length > 0 && (
          <ul className="workflow-blockers">
            {workflow.blockers.map((message) => (
              <li key={message}>{message}</li>
            ))}
          </ul>
        )}
        {real && (
          <p className="guide-note">
            Real API analysis · up to {data.limits.live_calls} model calls per
            scan.{" "}
            {workflow.public_footage_analysis_enabled
              ? "Recent public ESPN clips are imported automatically when a player match is available. Identity and tracking are checked before the footage supports a verdict."
              : "Footage is used only when processing is permitted; missing evidence stays visible in the report."}
          </p>
        )}
      </section>
    );
  }
  if (!real && simulated) {
    if (hasReport) return null;
    return (
      <section className="scouting-guide" aria-labelledby="guide-title">
        <span className="section-label">START WITH A SAMPLE</span>
        <h2 id="guide-title">Your first roster decision, explained.</h2>
        <p>
          Choose what your team needs below. TapeGrade compares free agents,
          checks their film, and suggests an add and drop when the evidence
          supports it.
        </p>
        <p className="guide-note">
          This sample uses fictional players and simulated analysis. No setup or
          API credits needed.
        </p>
      </section>
    );
  }

  const statsReady = !real || data.league.scouting_ready === true;
  const filmReady = !simulated && Boolean(status?.candidates.length);
  const movesReady = Boolean(status?.eligible_pair_count);
  const canScan = status?.ready ?? data.league.scouting_ready !== false;
  const next =
    real && simulated
      ? {
          title: "Your roster is connected. Live analysis is unavailable.",
          text: "Explore your roster, or switch to the sample league to try the complete scouting workflow.",
          action: "Open sample league options",
          destination: "connect" as const,
          section: undefined,
        }
      : !statsReady
        ? {
            title: "Next: prepare your league data.",
            text: "Confirm your scoring rules and load recent game logs so players can be compared fairly.",
            action: "Set up league data",
            destination: "data" as const,
            section: "statistics" as const,
          }
        : !filmReady && !canScan
          ? {
              title: "Next: add film for a free agent.",
              text: "Upload a short clip of a player with recent scores. TapeGrade will check the player’s identity and tracking before using it as evidence.",
              action: "Add player film",
              destination: "library" as const,
              section: undefined,
            }
          : real && !movesReady
            ? {
                title: "Ready for a scouting report.",
                text: "You can analyze players now. For an add/drop recommendation, first check a free agent’s availability and a roster player’s drop locks in Sleeper.",
                action: "Review player availability",
                destination: "data" as const,
                section: "eligibility" as const,
              }
            : {
                title: "Ready to find your next move.",
                text: "Choose what your team needs below. Film quality, current availability and your saved limits are checked before a move is recommended.",
                action: "Review scouting preferences",
                destination: "settings" as const,
                section: undefined,
              };
  const steps = [
    {
      label: "League data",
      ready: statsReady,
      destination: "data" as const,
      section: "statistics" as const,
    },
    {
      label: "Player film",
      ready: filmReady,
      destination: "library" as const,
      section: undefined,
    },
    ...(real
      ? [
          {
            label: "Add/drop eligibility",
            ready: movesReady,
            destination: "data" as const,
            section: "eligibility" as const,
          },
        ]
      : []),
  ];
  return (
    <section className="scouting-guide" aria-labelledby="guide-title">
      <span className="section-label">
        {canScan ? "YOUR NEXT STEP" : "GET READY TO SCOUT"}
      </span>
      <h2 id="guide-title">{next.title}</h2>
      <p>{next.text}</p>
      <div className="readiness-steps" aria-label="Scouting readiness">
        {steps.map((step) => (
          <button
            key={step.label}
            onClick={() => onNavigate(step.destination, step.section)}
          >
            {step.ready ? (
              <Check size={16} className="positive" />
            ) : (
              <Circle size={16} />
            )}
            <span>
              {step.label}
              <small>{step.ready ? "Ready" : "Needs review"}</small>
            </span>
            <ArrowRight size={14} />
          </button>
        ))}
      </div>
      <button
        className="button subtle"
        onClick={() => onNavigate(next.destination, next.section)}
      >
        {next.action}
        <ArrowRight size={15} />
      </button>
      {status && (status.blockers.length > 0 || status.notice) && (
        <details className="readiness-details">
          <summary>What’s available in this workspace?</summary>
          {status.blockers.length > 0 && (
            <ul>
              {status.blockers.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          )}
          {status.notice && <p>{status.notice}</p>}
        </details>
      )}
      {!simulated && status && status.candidates.length > 0 && (
        <p className="guide-note">
          Ready for identity and film checks:{" "}
          {status.candidates.map((p) => p.name).join(", ")}.
        </p>
      )}
    </section>
  );
}
