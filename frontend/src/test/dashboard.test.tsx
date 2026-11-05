import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import App from "../pages/App";
import { FilmPlayer } from "../components/FilmPlayer";
import { Recommendation } from "../components/Recommendation";
import { Library } from "../pages/Library";
import fixture from "./fixture.json";
import type { Candidate, Scan } from "../types";

const scan = fixture.scan as Scan;

async function openSavedScan() {
  fireEvent.click(await screen.findByRole("button", { name: /Scan history/ }));
  fireEvent.click(
    screen.getByRole("button", { name: new RegExp(scan.instruction) }),
  );
}
describe("scouting dashboard", () => {
  it("shows empty film without inventing measurements", () => {
    render(<FilmPlayer />);
    expect(screen.getByText("No clip analyzed yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Play clip" })).toBeDisabled();
    expect(screen.queryByText("75")).not.toBeInTheDocument();
  });
  it("renders stored measurements, unavailable metrics and toggles overlays", () => {
    render(<FilmPlayer candidate={scan.result!.candidates[0] as Candidate} />);
    expect(screen.getByText("On-ball involvement")).toBeInTheDocument();
    expect(screen.getAllByText("Unavailable")).toHaveLength(2);
    expect(
      screen.getByLabelText("Segmentation and bounding box overlay"),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Toggle segmentation overlays" }),
    );
    expect(
      screen.queryByLabelText("Segmentation and bounding box overlay"),
    ).not.toBeInTheDocument();
  });
  it("copies a labeled recommendation without offering transaction submission", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    render(<Recommendation scan={scan} onToast={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Copy move summary/ }));
    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith(
        expect.stringContaining("SIMULATED DEMO"),
      ),
    );
    expect(writeText.mock.calls[0][0]).toContain("FAAB $8");
    expect(screen.getByText("Review before you act.")).toBeInTheDocument();
  });
  it("submits the user mission and displays the persisted scan and guardrails", async () => {
    let submitted = false;
    const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
      let data: unknown;
      if (url === "/api/bootstrap") data = fixture.bootstrap;
      else if (url === "/api/scans" && options?.method === "POST") {
        submitted = true;
        data = { id: scan.id };
      } else if (url === "/api/scans") data = submitted ? [scan] : [];
      else if (url === `/api/scans/${scan.id}`) data = scan;
      else throw new Error(`Unexpected URL ${url}`);
      return { ok: true, json: async () => data };
    });
    vi.stubGlobal("fetch", fetcher);
    render(<App />);
    await screen.findByRole("button", { name: /Run (sample )?scan/ });
    fireEvent.change(screen.getByLabelText("Scouting mission"), {
      target: { value: "Find me a guard" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Run (sample )?scan/ }));
    await screen.findByText("Review before you act.");
    expect(
      fetcher.mock.calls.some(
        ([url, options]) =>
          url === "/api/scans" &&
          options?.body ===
            JSON.stringify({
              instruction: "Find me a guard",
              league_id: fixture.bootstrap.league.id,
            }),
      ),
    ).toBe(true);
    expect(
      screen.getByText(/Tracking quality insufficient/),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Download PNG/ })).toHaveAttribute(
      "href",
      `/api/scans/${scan.id}/card`,
    );
    fireEvent.click(screen.getByRole("button", { name: "Guardrails" }));
    expect(
      screen.getByRole("button", { name: /Save guardrails/ }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/Jordan Sterling/)).toBeChecked();
  });
  it("keeps real film diagnostics separate from fictional statistics and moves", async () => {
    const diagnostic = structuredClone(scan);
    diagnostic.mode = "live";
    diagnostic.result!.film_test = true;
    diagnostic.result!.simulated = false;
    diagnostic.result!.staged_move = null;
    diagnostic.result!.card = null;
    const subject = diagnostic.result!.candidates[0].player;
    subject.name = "Visible ball handler";
    subject.film_only = true;
    subject.is_demo = false;
    subject.number = null;
    subject.minutes = subject.previous_minutes = subject.fantasy_points = null;
    subject.stats = {};
    diagnostic.result!.candidates = [diagnostic.result!.candidates[0]];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => ({
        ok: true,
        json: async () =>
          url === "/api/bootstrap"
            ? { ...fixture.bootstrap, models_mode: "live" }
            : url === "/api/scans"
              ? [diagnostic]
              : diagnostic,
      })),
    );
    render(<App />);
    await openSavedScan();
    await screen.findByText("Film test · stats unavailable");
    expect(screen.getByText("Film review only")).toBeInTheDocument();
    expect(
      screen.getByText(
        /Game date, fantasy eligibility and statistics are unverified/,
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/#null/)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Copy move summary/ }),
    ).not.toBeInTheDocument();
  });
  it("connects a direct NBA league and shows actual period points without fabricated trends", async () => {
    let connected = false;
    const live = structuredClone(
      fixture.bootstrap,
    ) as import("../types").Bootstrap;
    live.demo_mode = false;
    live.league = {
      ...live.league,
      id: "sleeper:123",
      name: "Live test league",
      team_name: "Scout",
      is_demo: false,
      period: 3,
      period_points: 24.5,
      scouting_ready: false,
      scouting_unavailable_reason: "Recent statistics unavailable.",
      connection: {
        username: "scout",
        league_id: "123",
        user_id: "7",
        roster_id: 1,
      },
      notice: "Sleeper-reported period points; minutes and trends unavailable.",
      roster: live.league.roster.slice(0, 2).map((p, i) => ({
        ...p,
        id: `sleeper:123:${i}`,
        name: `Live Player ${i}`,
        is_demo: false,
        fantasy_points: i === 0 ? 24.5 : 0,
        minutes: null,
        previous_minutes: null,
        stats: {},
        trend: [],
        lineup_status: "Starter",
      })),
      available: [],
    };
    live.settings.protected_players = [];
    const fetcher = vi.fn(async (url: string, _options?: RequestInit) => {
      let data: unknown;
      if (url === "/api/sleeper/connect") {
        connected = true;
        data = { connected: true };
      } else if (url === "/api/bootstrap")
        data = connected ? live : fixture.bootstrap;
      else if (url === "/api/scans") data = [];
      else throw new Error(`Unexpected URL ${url}`);
      return { ok: true, json: async () => data };
    });
    vi.stubGlobal("fetch", fetcher);
    render(<App />);
    fireEvent.click(
      await screen.findByRole("button", { name: /Connect Sleeper/ }),
    );
    fireEvent.change(screen.getByLabelText("Sleeper username"), {
      target: { value: "scout" },
    });
    fireEvent.change(screen.getByLabelText("NBA league ID"), {
      target: { value: "123" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Connect NBA league" }));
    await screen.findByText("Live Player 0");
    expect(screen.getByText("PERIOD 3 FPTS")).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "24.5" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "0" })).toBeInTheDocument();
    expect(screen.getAllByText("Unavailable")).toHaveLength(2);
    expect(
      screen.queryByText("Fictional sample roster"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("img", { name: "Seven-game sample trend" }),
    ).not.toBeInTheDocument();
    expect(
      fetcher.mock.calls.some(
        ([url, options]) =>
          url === "/api/sleeper/connect" &&
          options?.body ===
            JSON.stringify({ username: "scout", league_id: "123" }),
      ),
    ).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Scouting desk" }));
    expect(
      screen.getByRole("button", { name: /Run (sample )?scan/ }),
    ).toBeDisabled();
  });
  it("shows backend errors without marking a failed request complete", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
        json: async () => ({ detail: "Backend unavailable" }),
      }),
    );
    render(<App />);
    expect(await screen.findByText("Backend unavailable")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Retry connection" }),
    ).toBeInTheDocument();
  });
});

it("renders non-FAAB real recommendations without a fabricated dollar amount", async () => {
  const real = structuredClone(scan);
  real.mode = "live";
  real.result!.league_is_demo = false;
  real.result!.staged_move!.faab_bid = null;
  const writeText = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal("navigator", { clipboard: { writeText } });
  render(<Recommendation scan={real} onToast={vi.fn()} />);
  expect(screen.getByText("No bid applies")).toBeInTheDocument();
  expect(screen.queryByText(/sample FAAB/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Copy move summary/ }));
  await waitFor(() =>
    expect(writeText).toHaveBeenCalledWith(
      expect.stringContaining("No FAAB bid applies"),
    ),
  );
  expect(writeText.mock.calls[0][0]).toContain("live Sleeper league report");
  expect(writeText.mock.calls[0][0]).not.toContain("$null");
});

it("opens league setup with explicit missing data and import controls", async () => {
  const live = structuredClone(
    fixture.bootstrap,
  ) as import("../types").Bootstrap;
  live.league.is_demo = false;
  live.league.scouting_ready = false;
  live.league.readiness_reasons = [
    "Technical and flagrant foul coverage is missing.",
  ];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => ({
      ok: true,
      json: async () =>
        url === "/api/bootstrap"
          ? live
          : url === "/api/stats"
            ? {
                provider: "none",
                provider_configured: false,
                summary: null,
                jobs: [],
              }
            : [],
    })),
  );
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "League setup" }));
  expect(
    await screen.findByText("Technical and flagrant foul coverage is missing."),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Import licensed JSON" }),
  ).toBeEnabled();
  fireEvent.click(screen.getByRole("tab", { name: "Rules" }));
  expect(screen.getByLabelText("Basketball mode")).toHaveValue("unknown");
  expect(
    screen.getByRole("button", { name: "Save verified rule evidence" }),
  ).toBeInTheDocument();
});

it("shows the owner-confirmed mode, FAAB budget and stacking rule", async () => {
  const live = structuredClone(
    fixture.bootstrap,
  ) as import("../types").Bootstrap;
  live.league.is_demo = false;
  live.league.scouting_ready = false;
  live.league.rules = {
    game_mode: "lock_in",
    waiver_mode: "faab",
    point_bonus_mode: "stack",
    faab_budget: 100,
    source_ref: "League owner confirmation in chat",
  };
  live.league.readiness_reasons = ["No recent statistics snapshot."];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => ({
      ok: true,
      json: async () =>
        url === "/api/bootstrap"
          ? live
          : url === "/api/stats"
            ? {
                provider: "none",
                provider_configured: false,
                summary: null,
                jobs: [],
              }
            : [],
    })),
  );
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "League setup" }));
  fireEvent.click(await screen.findByRole("tab", { name: "Rules" }));
  expect(await screen.findByLabelText("Basketball mode")).toHaveValue(
    "lock_in",
  );
  expect(screen.getByLabelText("Waiver mode")).toHaveValue("faab");
  expect(screen.getByLabelText("40/50-point bonuses")).toHaveValue("stack");
  expect(screen.getByLabelText("FAAB season budget ($)")).toHaveValue(100);
  expect(
    screen.queryByText(/Review and save protected-player selections/),
  ).not.toBeInTheDocument();
});

it("allows scouting with unknown eligibility and keeps refresh controls separate", async () => {
  const live = structuredClone(
    fixture.bootstrap,
  ) as import("../types").Bootstrap;
  live.league.is_demo = false;
  live.league.scouting_ready = true;
  live.models_mode = "live";
  live.scan_readiness = {
    ready: true,
    blockers: [],
    notice:
      "Scouting report only: eligibility review is still required for an add/drop recommendation.",
    eligible_pair_count: 0,
    candidates: [
      {
        id: "real-candidate",
        name: "Test Scouting Subject",
        eligible_drop_ids: [],
        transaction_issues: ["Waiver status unknown"],
      },
    ],
  };
  const oldError =
    "No supported add/drop pair has current verified availability.";
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    const failed = url === "/api/scans" && options?.method === "POST";
    const data = failed
      ? { detail: oldError }
      : url === "/api/bootstrap"
        ? live
        : url === "/api/stats"
          ? {
              provider: "sportradar",
              provider_configured: true,
              summary: null,
              jobs: [],
            }
          : url === "/api/scans"
            ? []
            : { saved: true, id: "refresh-job" };
    return { ok: !failed, status: failed ? 409 : 200, json: async () => data };
  });
  vi.stubGlobal("fetch", fetcher);
  render(<App />);
  const run = await screen.findByRole("button", { name: /Run (sample )?scan/ });
  expect(run).toBeEnabled();
  expect(screen.getByText(/Scouting report only:/)).toBeInTheDocument();
  expect(screen.getByText(/Test Scouting Subject/)).toBeInTheDocument();
  fireEvent.click(run);
  await screen.findByText(oldError);
  fireEvent.click(screen.getByRole("button", { name: "League setup" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "Refresh Sleeper roster" }),
  );
  await screen.findByText(/Sleeper roster and rules refreshed/);
  expect(screen.queryByText(oldError)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Refresh game logs" }));
  await screen.findByText(/Game-log refresh queued/);
  expect(
    fetcher.mock.calls.filter(([url]) => url === "/api/sleeper/refresh"),
  ).toHaveLength(1);
  expect(
    fetcher.mock.calls.filter(([url]) => url === "/api/stats/refresh"),
  ).toHaveLength(1);
});

it("offers mission shortcuts and keeps the first scan focused", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => ({
      ok: true,
      json: async () => (url === "/api/bootstrap" ? fixture.bootstrap : []),
    })),
  );
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Find a wing" }));
  expect(screen.getByLabelText("Scouting mission")).toHaveValue(
    "Find me an undervalued wing.",
  );
  expect(screen.getByLabelText("Scouting mission")).toHaveFocus();
  expect(screen.getByText("Find your next opportunity.")).toBeInTheDocument();
  expect(screen.queryByLabelText("Scouted candidates")).not.toBeInTheDocument();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Scouting desk" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  fireEvent.click(screen.getByRole("button", { name: "Hide navigation" }));
  expect(
    screen.queryByRole("navigation", { name: "Main navigation" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Show navigation" }));
  expect(
    screen.getByRole("navigation", { name: "Main navigation" }),
  ).toBeVisible();
});

it("changes the player film while preserving the scan recommendation", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => ({
      ok: true,
      json: async () =>
        url === "/api/bootstrap"
          ? fixture.bootstrap
          : url === "/api/scans"
            ? [scan]
            : scan,
    })),
  );
  render(<App />);
  await openSavedScan();
  await screen.findByRole("heading", { name: "Cameron Reed" });
  screen.getByRole("region", { name: "Selected player report" }).scrollTop =
    700;
  fireEvent.click(screen.getByRole("button", { name: /Rank 2.*Jalen Mercer/ }));
  expect(
    screen.getByRole("heading", { name: "Jalen Mercer" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("region", { name: "Selected player report" }).scrollTop,
  ).toBe(0);
  expect(
    screen.getByRole("button", { name: /Rank 2.*Jalen Mercer/ }),
  ).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByText("Review before you act.")).toBeInTheDocument();
  expect(
    screen.getByText(/Best supported move across this scan/),
  ).toBeInTheDocument();
  expect(screen.queryByLabelText("Scouting mission")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Start another scan/ }));
  expect(screen.getByLabelText("Scouting mission")).toBeInTheDocument();
});

it("filters the roster by player and protection status", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => ({
      ok: true,
      json: async () => (url === "/api/bootstrap" ? fixture.bootstrap : []),
    })),
  );
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "My roster" }));
  expect(screen.getByRole("heading", { name: "My roster" })).toHaveFocus();
  const player = fixture.bootstrap.league.roster[0];
  fireEvent.change(screen.getByLabelText("Search roster"), {
    target: { value: player.name },
  });
  expect(
    screen.getByText(`1 of ${fixture.bootstrap.league.roster.length} players`),
  ).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Search roster"), {
    target: { value: "No matching player" },
  });
  expect(screen.getByText("No players match")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
  fireEvent.click(screen.getByRole("button", { name: "Protected" }));
  expect(
    screen.getByText(
      `${fixture.bootstrap.settings.protected_players.length} of ${fixture.bootstrap.league.roster.length} players`,
    ),
  ).toBeInTheDocument();
});

it("contains keyboard focus in the league dialog and restores the trigger", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => ({
      ok: true,
      json: async () => (url === "/api/bootstrap" ? fixture.bootstrap : []),
    })),
  );
  render(<App />);
  const trigger = await screen.findByRole("button", {
    name: "Connect Sleeper",
  });
  trigger.focus();
  fireEvent.click(trigger);
  expect(screen.getByLabelText("Sleeper username")).toHaveFocus();
  const last = screen.getByRole("button", { name: /Continue with the sample/ });
  last.focus();
  fireEvent.keyDown(last, { key: "Tab" });
  expect(
    screen.getByRole("button", { name: "Close league connection" }),
  ).toHaveFocus();
  fireEvent.keyDown(document.activeElement!, { key: "Tab", shiftKey: true });
  expect(last).toHaveFocus();
  fireEvent.keyDown(last, { key: "Escape" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();
});

it("refreshes scan readiness after a film upload", async () => {
  const onRefresh = vi.fn().mockResolvedValue(undefined);
  const onToast = vi.fn();
  const onError = vi.fn();
  const fetcher = vi.fn(async (_url: string, options?: RequestInit) => ({
    ok: true,
    json: async () => (options?.method === "POST" ? { id: "new-clip" } : []),
  }));
  vi.stubGlobal("fetch", fetcher);
  render(
    <Library
      data={fixture.bootstrap as import("../types").Bootstrap}
      onRefresh={onRefresh}
      onToast={onToast}
      onError={onError}
    />,
  );
  await screen.findByText("No clips in your library");
  fireEvent.change(screen.getByLabelText("Target player"), {
    target: { value: fixture.bootstrap.league.available[0].id },
  });
  fireEvent.change(screen.getByLabelText("Video file"), {
    target: {
      files: [new File(["local test"], "test.mp4", { type: "video/mp4" })],
    },
  });
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.submit(
    screen.getByRole("button", { name: "Process local clip" }).closest("form")!,
  );
  await waitFor(() => expect(onRefresh).toHaveBeenCalledOnce());
  await waitFor(() =>
    expect(onToast).toHaveBeenCalledWith(
      "Clip saved. Return to scouting to review readiness.",
    ),
  );
  expect(
    fetcher.mock.calls.some(([, options]) => options?.method === "POST"),
  ).toBe(true);
});

it("opens a compact navigation drawer and returns to the chosen page", async () => {
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => ({
      ok: true,
      json: async () => (url === "/api/bootstrap" ? fixture.bootstrap : []),
    })),
  );
  render(<App />);
  const menu = await screen.findByRole("button", { name: "Show navigation" });
  expect(
    screen.queryByRole("navigation", { name: "Main navigation" }),
  ).not.toBeInTheDocument();
  menu.focus();
  fireEvent.click(menu);
  expect(screen.getByRole("dialog", { name: "Workspace" })).toBeInTheDocument();
  fireEvent.keyDown(document.activeElement!, { key: "Escape" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(menu).toHaveFocus();
  fireEvent.click(menu);
  fireEvent.click(screen.getByRole("button", { name: "My roster" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "My roster" })).toHaveFocus();
  expect(screen.getByLabelText("Search roster")).toBeInTheDocument();
});

it("preserves setup form values and supports keyboard section navigation", async () => {
  const live = structuredClone(
    fixture.bootstrap,
  ) as import("../types").Bootstrap;
  live.league.is_demo = false;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => ({
      ok: true,
      json: async () =>
        url === "/api/bootstrap"
          ? live
          : url === "/api/stats"
            ? {
                provider: "none",
                provider_configured: false,
                summary: null,
                jobs: [],
              }
            : [],
    })),
  );
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "League setup" }));
  fireEvent.click(screen.getByRole("tab", { name: "Rules" }));
  fireEvent.change(screen.getByLabelText("Verification source"), {
    target: { value: "Verified league settings reference" },
  });
  fireEvent.click(screen.getByRole("tab", { name: "Overview" }));
  expect(
    screen.queryByRole("button", { name: "Save verified rule evidence" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", { name: "Rules" }));
  expect(screen.getByLabelText("Verification source")).toHaveValue(
    "Verified league settings reference",
  );
  fireEvent.change(screen.getByLabelText("Basketball mode"), {
    target: { value: "lock_in" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Save verified rule evidence" }),
  );
  expect(await screen.findByText("Rule evidence saved.")).toBeVisible();
  expect(screen.getByRole("tab", { name: "Rules" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  fireEvent.keyDown(screen.getByRole("tab", { name: "Rules" }), {
    key: "ArrowRight",
  });
  expect(screen.getByRole("tab", { name: "Player identities" })).toHaveFocus();
  expect(
    screen.getByRole("tab", { name: "Player identities" }),
  ).toHaveAttribute("aria-selected", "true");
  expect(screen.getByLabelText("Identity verification source")).toBeVisible();
  fireEvent.keyDown(document.activeElement!, { key: "End" });
  expect(screen.getByRole("tab", { name: "Game logs" })).toHaveFocus();
  fireEvent.keyDown(document.activeElement!, { key: "Home" });
  expect(screen.getByRole("tab", { name: "Overview" })).toHaveFocus();
});

it("finds a saved scan and reopens its matching report", async () => {
  const older = structuredClone(scan);
  older.id = "older-report";
  older.instruction = "Earlier guard scouting report";
  const fetcher = vi.fn(async (url: string) => ({
    ok: true,
    json: async () =>
      url === "/api/bootstrap"
        ? fixture.bootstrap
        : url === "/api/scans"
          ? [scan, older]
          : url === `/api/scans/${older.id}`
            ? older
            : scan,
  }));
  vi.stubGlobal("fetch", fetcher);
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: /Scan history/ }));
  fireEvent.change(screen.getByLabelText("Search scan history"), {
    target: { value: "Earlier guard" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: /Earlier guard scouting report/ }),
  );
  expect(
    await screen.findByRole("heading", { name: older.instruction }),
  ).toBeInTheDocument();
  expect(
    fetcher.mock.calls.some(([url]) => url === `/api/scans/${older.id}`),
  ).toBe(true);
  expect(
    screen.getByRole("heading", { name: "Scouting desk" }),
  ).toBeInTheDocument();
});
