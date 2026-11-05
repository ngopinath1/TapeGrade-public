import { ArrowRight, ShieldCheck } from "lucide-react";
import type { Bootstrap } from "../types";

export function ScanReadiness({
  data,
  onSetup,
}: {
  data: Bootstrap;
  onSetup?: () => void;
}) {
  const status = data.scan_readiness;
  if (!status || (data.league.is_demo !== false && status.ready)) return null;
  return (
    <div className="worker-note" role="status">
      <b>
        <ShieldCheck size={17} />{" "}
        {status.ready ? "Ready to scan." : "Before you scan."}
      </b>{" "}
      {status.blockers.join(" ")}
      {status.candidates.length > 0 && (
        <span>
          {status.candidates.length} player
          {status.candidates.length === 1 ? "" : "s"} with recent scores and
          usable film: {status.candidates.map((p) => p.name).join(", ")}.
          Footage identity and tracking quality are checked during the
          scan.{" "}
        </span>
      )}
      {status.notice && <p>{status.notice}</p>}
      {status.eligible_pair_count > 0 && (
        <p>
          {status.eligible_pair_count} add/drop pairs currently have eligibility
          evidence. Eligibility is checked again before a move is recommended.
        </p>
      )}
      {!status.ready && onSetup && (
        <button className="text-link" onClick={onSetup}>
          {data.league.is_demo === false
            ? "Open league setup"
            : "Add film in library"}{" "}
          <ArrowRight size={15} />
        </button>
      )}
    </div>
  );
}
