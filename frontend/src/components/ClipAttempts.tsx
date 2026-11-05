import { ArrowRightLeft, Check } from "lucide-react";
import type { Candidate } from "../types";

const outcomes: Record<string, string> = {
  identity_unclear: "Identity unclear",
  tracking_unclear: "Tracking unclear",
  no_usable_metrics: "No usable measurements",
  usable: "Evidence accepted",
  budget_limit: "Call limit preserved",
  source_unavailable: "Footage unavailable",
};
export function ClipAttempts({ candidate }: { candidate?: Candidate }) {
  const fallback = candidate?.clip_fallback;
  if (!fallback || (!fallback.notice && !fallback.tried_alternative))
    return null;
  return (
    <section className="clip-attempts" aria-label="Automatic clip selection">
      <div className="clip-attempts-heading">
        <ArrowRightLeft size={15} />
        <strong>
          {fallback.tried_alternative
            ? `Automatically checked ${fallback.attempted} ${fallback.same_highlight_excerpts ? "excerpts" : "clips"}`
            : "Clip selection"}
        </strong>
      </div>
      {fallback.notice && <p>{fallback.notice}</p>}
      {fallback.same_highlight_excerpts && (
        <p>
          These are different excerpts of the same publisher highlight. They
          show the same play, not independent game samples.
        </p>
      )}
      <details>
        <summary>See clip checks</summary>
        <ol>
          {candidate?.clip_attempts?.map((attempt) => (
            <li key={attempt.number}>
              <div>
                <strong>
                  Clip {attempt.number}
                  {attempt.selected ? " · Shown in this report" : ""}
                </strong>
                <span className="tag">
                  {attempt.selected && attempt.outcome === "usable" && (
                    <Check size={12} />
                  )}{" "}
                  {outcomes[attempt.outcome] ?? attempt.outcome}
                </span>
              </div>
              {attempt.source_ref?.startsWith("https://") && (
                <a href={attempt.source_ref} target="_blank" rel="noreferrer">
                  {attempt.source_title ?? "View source footage"}
                </a>
              )}
              <p>{attempt.reason}</p>
              {attempt.source_span && (
                <small>
                  Source excerpt: {attempt.source_span.start.toFixed(1)}–
                  {attempt.source_span.end.toFixed(1)}s
                </small>
              )}
            </li>
          ))}
        </ol>
      </details>
    </section>
  );
}
