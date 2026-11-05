import { useEffect, useRef, useState } from "react";
import { ArrowRight, ArrowUpRight, ChevronDown, RefreshCw } from "lucide-react";
import type { Bootstrap, Scan } from "../types";
import { Candidates } from "../components/Candidates";
import { FilmPlayer } from "../components/FilmPlayer";
import { Recommendation } from "../components/Recommendation";
import { PerceptionLog } from "../components/PerceptionLog";
import { TapeCard } from "../components/TapeCard";
import { ScanReadiness } from "../components/ScanReadiness";
import { ScoutingRequest } from "../components/ScoutingRequest";
import { ScanProgress } from "../components/ScanProgress";
import type {
  GuideDestination,
  SetupSection,
} from "../components/ScoutingGuide";

export function ScoutingDesk({
  data,
  scan,
  busy,
  instruction,
  onInstruction,
  selected,
  onSelect,
  onRun,
  onRetry,
  onWatch,
  onNavigate,
  onToast,
}: {
  data: Bootstrap;
  scan: Scan | null;
  busy: boolean;
  instruction: string;
  onInstruction: (value: string) => void;
  selected: string;
  onSelect: (id: string) => void;
  onRun: () => Promise<void>;
  onRetry: () => Promise<void>;
  onWatch: (id: string) => Promise<void>;
  onNavigate: (page: GuideDestination, section?: SetupSection) => void;
  onToast: (message: string) => void;
}) {
  const [missionOpen, setMissionOpen] = useState(!scan?.result);
  const input = useRef<HTMLInputElement>(null);
  const detail = useRef<HTMLDivElement>(null);
  const automatic =
    data.workflow?.automatic === true && data.models_mode === "live";
  const ready =
    data.workflow && data.models_mode === "live"
      ? data.workflow.can_start
      : data.models_mode === "mock" && data.league.is_demo === false
        ? false
        : (data.scan_readiness?.ready ?? data.league.scouting_ready !== false);
  const simulated =
    data.models_mode === "mock" && data.league.is_demo !== false;
  const candidates = scan?.result?.candidates ?? [];
  const current =
    candidates.find((c) => c.player.id === selected) ?? candidates[0];
  useEffect(() => {
    if (detail.current) detail.current.scrollTop = 0;
  }, [current?.player.id]);
  useEffect(() => {
    if (scan?.result) setMissionOpen(false);
  }, [scan?.id, Boolean(scan?.result)]);
  const provenance = scan?.result?.film_test
    ? "Film diagnostic · game date and fantasy statistics unverified"
    : data.league.is_demo === false
      ? "Sleeper NBA · sourced game logs required"
      : (scan?.mode ?? data.models_mode) === "mock"
        ? "Demo report · fictional players and simulated models"
        : "Live model report · fictional sample league statistics";
  return (
    <>
      {!automatic && scan?.result && (
        <ScanReadiness
          data={data}
          onSetup={() =>
            onNavigate(data.league.is_demo === false ? "data" : "library")
          }
        />
      )}
      {!automatic &&
        data.league.is_demo === false &&
        !data.scan_readiness &&
        !ready && (
          <div className="worker-note">
            <strong>Finish league setup to scan.</strong>
            <p>{data.league.scouting_unavailable_reason}</p>
            <button className="text-link" onClick={() => onNavigate("data")}>
              Open league setup
            </button>
          </div>
        )}
      {scan?.result && (
        <div className="report-toolbar">
          <div>
            <h2>{scan.instruction}</h2>
            <p>
              {new Date(scan.created_at).toLocaleString(undefined, {
                month: "short",
                day: "numeric",
                hour: "numeric",
                minute: "2-digit",
              })}
              <span>·</span>
              {provenance}
            </p>
          </div>
          <button
            className="button"
            aria-expanded={missionOpen}
            onClick={() => {
              setMissionOpen(!missionOpen);
              if (!missionOpen)
                requestAnimationFrame(() => input.current?.focus());
            }}
          >
            {missionOpen ? "Close new scan" : "Start another scan"}
          </button>
        </div>
      )}
      {!busy && (!scan?.result || missionOpen) && (
        <ScoutingRequest
          data={data}
          hasReport={Boolean(scan?.result)}
          busy={busy}
          canScan={ready}
          simulated={simulated}
          instruction={instruction}
          setInstruction={onInstruction}
          inputRef={input}
          onRun={onRun}
          onNavigate={onNavigate}
        />
      )}
      {busy && <ScanProgress scan={scan} />}
      {scan?.stage === "FAILED" && (
        <div className="error-banner" role="alert">
          <div>
            <p>
              {scan.error ??
                "This scan could not finish. Check the connection and retry."}
            </p>
            <p>
              Saved work is retained. Retrying a live scan may use additional
              API credits within its call limit.
            </p>
          </div>
          <button className="button" onClick={() => void onRetry()}>
            <RefreshCw size={15} /> Retry scan
          </button>
          {scan.action_needed && (
            <button
              className="button"
              onClick={() =>
                onNavigate(
                  scan.action_needed!.destination,
                  scan.action_needed!.section,
                )
              }
            >
              {scan.action_needed.label}
              <ArrowRight size={14} />
            </button>
          )}
        </div>
      )}
      {scan?.result?.film_test && (
        <div className="worker-note">
          Film diagnostic · user-provided excerpt · visible jersey target only.
          Game date, fantasy eligibility and statistics are unverified. No
          roster move is recommended.
        </div>
      )}
      {scan?.result && (
        <div className="report-workspace">
          <Candidates
            emptyReason={scan.result.shortlist.reasoning}
            candidates={candidates}
            selected={current?.player.id ?? ""}
            onSelect={onSelect}
            watchlist={data.watchlist}
            onWatch={(id) => void onWatch(id)}
          />
          <div
            ref={detail}
            className="report-detail"
            role="region"
            aria-label="Selected player report"
            tabIndex={0}
          >
            {current && !current.clip ? (
              <section className="footage-evidence">
                <h2>No footage analyzed for {current.player.name}</h2>
                <p>
                  {current.footage_notice ??
                    "No permitted clip was available. Film measurements and film-backed add recommendations are withheld."}
                </p>
                {Boolean(current.footage_sources?.length) && (
                  <>
                    <h3>Footage found on the publisher’s site</h3>
                    <p>
                      Viewing links only. These clips were not downloaded or
                      analyzed.
                    </p>
                    <ul>
                      {current.footage_sources!.map((source) => (
                        <li key={source.url}>
                          <a href={source.url} target="_blank" rel="noreferrer">
                            {source.title}
                            <ArrowUpRight size={13} />
                          </a>
                          <small>
                            {source.publisher} · {source.game_date}
                          </small>
                        </li>
                      ))}
                    </ul>
                  </>
                )}
                <button
                  className="button"
                  onClick={() => onNavigate("library")}
                >
                  Add permitted footage
                  <ArrowRight size={14} />
                </button>
              </section>
            ) : current ? (
              <FilmPlayer candidate={current} />
            ) : null}
            <Recommendation scan={scan} onToast={onToast} />
            <details className="audit-disclosure">
              <summary>
                <span>Tracking & evidence details</span>
                <ChevronDown size={16} />
              </summary>
              <PerceptionLog scan={scan} selected={current} />
            </details>
            <TapeCard scan={scan} />
          </div>
        </div>
      )}
    </>
  );
}
