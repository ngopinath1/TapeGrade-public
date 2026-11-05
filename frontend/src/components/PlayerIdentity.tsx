import { Check, CircleHelp, ExternalLink } from "lucide-react";
import type { Candidate } from "../types";

export function PlayerIdentity({ candidate }: { candidate?: Candidate }) {
  const identity = candidate?.identity;
  if (!identity) return null;
  const confirmed = identity.status === "corroborated";
  return (
    <section className="identity-proof" aria-label="Player identity evidence">
      <div className="identity-proof-heading">
        <div>
          <h3>How was this player identified?</h3>
          <p>
            Expected from the game roster: {identity.expected_name} ·{" "}
            {identity.expected_team} #{identity.expected_jersey ?? "unknown"}
          </p>
        </div>
        <span className={`tag ${confirmed ? "positive" : ""}`}>
          {confirmed ? <Check size={14} /> : <CircleHelp size={14} />}
          {confirmed
            ? "Identity corroborated"
            : identity.status === "tracking_rejected"
              ? "Tracking identity uncertain"
              : "Identity unconfirmed"}
        </span>
      </div>
      <p>
        {confirmed
          ? "The visible jersey and team match the dated roster. That player is bound to tracking ID 1 and checked across multiple frames."
          : "A source title or roster match alone does not identify a person in the video. Uncertain or conflicting evidence withholds the identity or tracking measurements."}
      </p>
      {identity.reasons.length > 0 && (
        <ul className="identity-reasons">
          {identity.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}
      {identity.source_ref?.startsWith("https://") && (
        <a
          className="text-link"
          href={identity.source_ref}
          target="_blank"
          rel="noreferrer"
        >
          Check the game roster · {identity.source_date}
          <ExternalLink size={13} />
        </a>
      )}
      {identity.evidence.length > 0 && (
        <div className="identity-anchors">
          {identity.evidence.map((item) => (
            <figure key={item.frame}>
              <a href={item.source_url} target="_blank" rel="noreferrer">
                <img
                  src={item.crop_url}
                  alt={`Jersey ${item.jersey_number} evidence at ${item.time.toFixed(1)} seconds`}
                  loading="lazy"
                />
              </a>
              <figcaption>
                {item.time.toFixed(1)}s · {item.team} #{item.jersey_number}
                <small>{item.evidence}</small>
              </figcaption>
            </figure>
          ))}
        </div>
      )}
      <details className="identity-bindings">
        <summary>Player names and tracking IDs</summary>
        <p>
          Names use visible jersey readings matched to the game roster.
          Unreadable players stay unnamed. These names identify the seed-frame
          players; tracking quality is checked separately.
        </p>
        <ul>
          {identity.tracked_players
            .filter((item) => item.role !== "ball")
            .map((item) => (
              <li key={item.object_id}>
                <strong>Track {item.object_id}</strong> ·{" "}
                {confirmed
                  ? (item.name ?? "Unidentified player")
                  : "Identity not confirmed"}
                {item.team ? ` · ${item.team}` : ""}
                {item.jersey_number ? ` #${item.jersey_number}` : ""}
                <small>
                  {item.role === "target"
                    ? "Requested player"
                    : "Opposing player"}
                </small>
              </li>
            ))}
        </ul>
      </details>
    </section>
  );
}
