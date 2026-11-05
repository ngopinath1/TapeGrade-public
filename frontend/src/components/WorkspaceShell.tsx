import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  Film,
  History,
  LayoutDashboard,
  PanelLeft,
  Settings2,
  ShieldCheck,
  Users,
  X,
  ArrowUpRight,
} from "lucide-react";
import type { Bootstrap } from "../types";
import { useDialogFocus } from "../hooks/useDialogFocus";

export type Page =
  "desk" | "roster" | "library" | "history" | "settings" | "data";
const titles: Record<Page, string> = {
  desk: "Scouting desk",
  roster: "My roster",
  library: "Film library",
  history: "Scan history",
  settings: "Guardrails",
  data: "League setup",
};

export function WorkspaceShell({
  data,
  page,
  historyCount,
  onNavigate,
  onConnect,
  children,
}: {
  data: Bootstrap;
  page: Page;
  historyCount: number;
  onNavigate: (page: Page) => void;
  onConnect: () => void;
  children: ReactNode;
}) {
  const [compact, setCompact] = useState(
    () =>
      typeof window.matchMedia === "function" &&
      window.matchMedia("(max-width: 760px)").matches,
  );
  const [sidebarShown, setSidebarShown] = useState(true);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const drawer = useRef<HTMLElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia("(max-width: 760px)");
    const update = () => {
      setCompact(media.matches);
      setDrawerOpen(false);
    };
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  useDialogFocus(compact && drawerOpen, drawer, () => setDrawerOpen(false));
  useEffect(() => {
    document.title = `${titles[page]} · TapeGrade`;
    heading.current?.focus({ preventScroll: true });
  }, [page]);
  const shown = compact ? drawerOpen : sidebarShown;
  const navigate = (next: Page) => {
    setDrawerOpen(false);
    onNavigate(next);
  };
  const connect = () => {
    setDrawerOpen(false);
    onConnect();
  };
  const nav = [
    { id: "desk" as Page, label: "Scouting desk", icon: LayoutDashboard },
    { id: "roster" as Page, label: "My roster", icon: Users },
    { id: "library" as Page, label: "Film library", icon: Film },
    { id: "history" as Page, label: "Scan history", icon: History },
    ...(data.league.is_demo === false
      ? [{ id: "data" as Page, label: "League setup", icon: ShieldCheck }]
      : []),
    { id: "settings" as Page, label: "Guardrails", icon: Settings2 },
  ];
  return (
    <div
      className={`app-shell ${!compact && !sidebarShown ? "navigation-hidden" : ""}`}
    >
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      {compact && drawerOpen && (
        <div
          className="navigation-scrim"
          onClick={() => setDrawerOpen(false)}
          aria-hidden="true"
        />
      )}
      <aside
        ref={drawer}
        id="workspace-navigation"
        className={`sidebar ${compact ? "navigation-drawer" : ""}`}
        hidden={!shown}
        role={compact ? "dialog" : undefined}
        aria-modal={compact && drawerOpen ? true : undefined}
        aria-label="Workspace"
      >
        <div className="sidebar-heading">
          <button className="brand" onClick={() => navigate("desk")}>
            TapeGrade
          </button>
          {compact && (
            <button
              className="icon-button"
              aria-label="Close navigation"
              onClick={() => setDrawerOpen(false)}
            >
              <X size={19} />
            </button>
          )}
        </div>
        <button
          className="workspace-switch"
          onClick={connect}
          aria-label={`Change league: ${data.league.name}`}
        >
          <span>
            <strong>{data.league.name}</strong>
            <small>
              {data.league.is_demo === false ? "Sleeper NBA" : "Sample league"}
            </small>
          </span>
          <ArrowUpRight size={14} aria-hidden="true" />
        </button>
        <nav aria-label="Main navigation">
          {nav.map((item) => (
            <button
              key={item.id}
              aria-current={page === item.id ? "page" : undefined}
              className={page === item.id ? "active" : ""}
              onClick={() => navigate(item.id)}
            >
              <item.icon size={18} />
              <span>{item.label}</span>
              {item.id === "history" && historyCount > 0 && (
                <span
                  className="nav-count"
                  aria-label={`${historyCount} unreviewed ${historyCount === 1 ? "scan" : "scans"}`}
                >
                  {historyCount}
                </span>
              )}
            </button>
          ))}
        </nav>
        <a
          className="help-link"
          href="http://localhost:8000/docs"
          target="_blank"
          rel="noreferrer"
        >
          API reference
        </a>
      </aside>
      <div
        className="main-shell"
        inert={compact && drawerOpen ? true : undefined}
      >
        <header className="topbar">
          <div className="toolbar-title">
            <button
              className="icon-button"
              aria-label={shown ? "Hide navigation" : "Show navigation"}
              aria-expanded={shown}
              aria-controls="workspace-navigation"
              onClick={() =>
                compact
                  ? setDrawerOpen(!drawerOpen)
                  : setSidebarShown(!sidebarShown)
              }
            >
              <PanelLeft size={20} />
            </button>
            <h1 ref={heading} tabIndex={-1}>
              {titles[page]}
            </h1>
          </div>
          <div className="top-actions">
            <span className="mode-pill">
              {data.models_mode === "mock" ? "Demo models" : "Live models"}
            </span>
            <button
              className="button toolbar-button"
              onClick={connect}
              aria-label={
                data.league.is_demo === false
                  ? "Manage connection"
                  : "Connect Sleeper"
              }
            >
              <span className="connection-title">
                {data.league.is_demo === false
                  ? "Manage connection"
                  : "Connect Sleeper"}
              </span>
              <span className="connection-short-title" aria-hidden="true">
                League
              </span>
            </button>
          </div>
        </header>
        <main
          id="main-content"
          className={`main-content page-${page}`}
          tabIndex={-1}
        >
          <div key={page} className="view-appear">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
