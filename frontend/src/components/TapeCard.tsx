import { ArrowDownToLine } from "lucide-react";
import type { Scan } from "../types";

export function TapeCard({ scan }: { scan: Scan | null }) {
  const card = scan?.result?.card;
  return (
    <section className="report-downloads" aria-label="Report downloads">
      <div className="download-actions">
        {card && (
          <a className="button" href={`/api/scans/${scan?.id}/card`} download>
            <ArrowDownToLine size={15} /> Download PNG{" "}
            <small>1080 × 1350</small>
          </a>
        )}
        {scan?.result && (
          <a
            className="button"
            href={`/api/scans/${scan.id}/evidence`}
            download
          >
            Download evidence JSON
          </a>
        )}
      </div>
      {card ? (
        <details className="card-preview">
          <summary>
            Preview Tape Card{" "}
            <span>
              {card.simulated
                ? "Simulated artwork"
                : card.visual_source.startsWith("Local")
                  ? "Evidence card"
                  : "Muse Image artwork"}
            </span>
          </summary>
          <a
            href={`/api/scans/${scan?.id}/card`}
            download
            className="card-image"
          >
            <img
              src={card.url}
              alt="Scouting Tape Card with report metrics"
              loading="lazy"
            />
          </a>
        </details>
      ) : (
        <p className="data-note">
          {scan?.result?.card_error ??
            "The Tape Card will be available when the report is ready."}
        </p>
      )}
    </section>
  );
}
