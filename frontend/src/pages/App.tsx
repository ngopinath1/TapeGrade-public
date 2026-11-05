import { useEffect, useState } from "react";
import { Check, Loader2, X } from "lucide-react";
import { WorkspaceShell, type Page } from "../components/WorkspaceShell";
import { SleeperDialog } from "../components/SleeperDialog";
import { Roster } from "../components/Roster";
import { ScoutingDesk } from "./ScoutingDesk";
import { ScanHistory } from "./ScanHistory";
import { DataSetup } from "./DataSetup";
import { Settings } from "./Settings";
import { Library } from "./Library";
import type {
  GuideDestination,
  SetupSection,
} from "../components/ScoutingGuide";
import { useDashboard } from "../hooks/useDashboard";
import { useAppearance } from "../hooks/useAppearance";
import { api, complete } from "../lib/api";

export default function App() {
  const {
    data,
    history,
    scan: savedScan,
    scanId,
    error,
    setError,
    run,
    refresh,
    setScanId,
    reloadScan,
    markReviewed,
  } = useDashboard();
  const [appearance, setAppearance] = useAppearance();
  const [page, setPage] = useState<Page>("desk");
  const [instruction, setInstruction] = useState(
    "Find the best available upgrade for my roster.",
  );
  const [setupSection, setSetupSection] = useState<SetupSection>("statistics");
  const [selected, setSelected] = useState("");
  const [connecting, setConnecting] = useState(false);
  const [toast, setToast] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const scan = savedScan?.id === scanId ? savedScan : null;
  useEffect(() => {
    if (page === "desk" && scan && complete(scan.stage) && !scan.reviewed) {
      void markReviewed(scan);
    }
  }, [page, scan?.id, scan?.stage, scan?.attempts, markReviewed]);
  const busy =
    submitting || Boolean(scanId && (!scan || !complete(scan.stage)));
  const goTo = (next: Page) => {
    setPage(next);
    document.documentElement.scrollTop = 0;
    document.body.scrollTop = 0;
  };
  const navigate = (destination: GuideDestination, section?: SetupSection) => {
    if (destination === "connect") setConnecting(true);
    else {
      if (section) setSetupSection(section);
      goTo(destination);
    }
  };
  if (!data)
    return (
      <main className="startup">
        <strong className="startup-brand">TapeGrade</strong>
        {error ? (
          <>
            <h1>Unable to open the workspace</h1>
            <p role="alert">{error}</p>
            <p>Start the backend on localhost:8000, then try again.</p>
            <button
              className="button primary"
              onClick={() => {
                setError("");
                void refresh();
              }}
            >
              Retry connection
            </button>
          </>
        ) : (
          <p role="status">
            <Loader2 className="spin" size={17} /> Opening your workspace…
          </p>
        )}
      </main>
    );
  return (
    <>
      <WorkspaceShell
        data={data}
        page={page}
        historyCount={
          history.filter((item) => complete(item.stage) && !item.reviewed)
            .length
        }
        onNavigate={goTo}
        onConnect={() => setConnecting(true)}
      >
        {error && (
          <div role="alert" className="error-banner">
            <span>{error}</span>
            <button
              className="icon-button"
              aria-label="Dismiss error"
              onClick={() => setError("")}
            >
              <X size={17} />
            </button>
          </div>
        )}
        {page === "desk" && (
          <ScoutingDesk
            data={data}
            scan={scan}
            busy={busy}
            instruction={instruction}
            onInstruction={setInstruction}
            selected={selected}
            onSelect={setSelected}
            onNavigate={navigate}
            onToast={setToast}
            onRun={async () => {
              setSubmitting(true);
              setSelected("");
              try {
                await run(instruction.trim());
              } finally {
                setSubmitting(false);
              }
            }}
            onRetry={async () => {
              if (!scan) return;
              try {
                await api(`/scans/${scan.id}/retry`, { method: "POST" });
                await reloadScan();
                setScanId(null);
                setTimeout(() => setScanId(scan.id), 0);
              } catch (e) {
                setError((e as Error).message);
              }
            }}
            onWatch={async (id) => {
              try {
                await api(`/watchlist/${id}`, { method: "POST" });
                await refresh();
              } catch (e) {
                setError((e as Error).message);
              }
            }}
          />
        )}
        {page === "roster" && (
          <Roster
            key={data.league.id}
            data={data}
            onManageProtections={() => goTo("settings")}
          />
        )}
        {page === "data" && data.league.is_demo === false && (
          <DataSetup
            key={data.league.id}
            initialSection={setupSection}
            onDone={() => goTo("desk")}
            data={data}
            onRefresh={refresh}
            onError={setError}
          />
        )}
        {page === "settings" && (
          <Settings
            key={data.league.id}
            data={data}
            appearance={appearance}
            onAppearance={setAppearance}
            onSave={async (value) => {
              try {
                await api("/settings", {
                  method: "PUT",
                  body: JSON.stringify(value),
                });
                await refresh();
                await reloadScan();
                setToast(
                  "Guardrails saved. Staged moves have been checked against your rules.",
                );
              } catch (e) {
                setError((e as Error).message);
                throw e;
              }
            }}
          />
        )}
        {page === "library" && (
          <Library
            key={data.league.id}
            data={data}
            onError={setError}
            onToast={setToast}
            onRefresh={refresh}
            onDone={() => goTo("desk")}
          />
        )}
        {page === "history" && (
          <ScanHistory
            scans={history}
            onOpen={(saved) => {
              setScanId(saved.id);
              setSelected("");
              goTo("desk");
            }}
            onStart={() => goTo("desk")}
          />
        )}
      </WorkspaceShell>
      {connecting && (
        <SleeperDialog
          connection={data.league.connection}
          close={() => setConnecting(false)}
          onConnected={async () => {
            await refresh(true);
            setSelected("");
            goTo("roster");
            setToast("League workspace updated.");
          }}
        />
      )}
      {toast && (
        <div role="status" className="toast">
          <Check size={17} />
          <span>{toast}</span>
          <button
            className="icon-button"
            aria-label="Dismiss notification"
            onClick={() => setToast("")}
          >
            <X size={17} />
          </button>
        </div>
      )}
    </>
  );
}
