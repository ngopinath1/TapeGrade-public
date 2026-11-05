import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import App from "../pages/App";
import { Library } from "../pages/Library";
import fixture from "./fixture.json";
import type { Bootstrap, Scan } from "../types";

function connected(): Bootstrap {
  const data = structuredClone(fixture.bootstrap) as Bootstrap;
  data.league.is_demo = false;
  data.models_mode = "live";
  data.league.scouting_ready = true;
  data.scan_readiness = {
    ready: true,
    blockers: [],
    notice: null,
    eligible_pair_count: 0,
    candidates: [
      {
        id: "free-agent",
        name: "Film candidate",
        eligible_drop_ids: [],
        transaction_issues: [],
      },
    ],
  };
  return data;
}
function mockApi(data: Bootstrap, scans: Scan[] = []) {
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    const result =
      url === "/api/bootstrap"
        ? data
        : url === "/api/scans" && options?.method === "POST"
          ? { id: fixture.scan.id }
          : url === "/api/scans"
            ? scans
            : url === "/api/stats"
              ? {
                  provider: "none",
                  provider_configured: false,
                  summary: null,
                  jobs: [],
                }
              : url === "/api/clips"
                ? []
                : url.endsWith("/review")
                  ? { reviewed: true }
                  : (scans[0] ?? fixture.scan);
    return { ok: true, json: async () => result };
  });
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}

async function openSavedScan() {
  fireEvent.click(await screen.findByRole("button", { name: /Scan history/ }));
  fireEvent.click(
    screen.getByRole("button", { name: new RegExp(fixture.scan.instruction) }),
  );
}

describe("guided scouting workflow", () => {
  it("starts with one usable sample action and keeps empty analysis panels out of the way", async () => {
    const fetcher = mockApi(fixture.bootstrap as Bootstrap);
    render(<App />);
    expect(
      await screen.findByRole("button", { name: "Run sample scan" }),
    ).toBeEnabled();
    expect(screen.getByText("Find your next opportunity.")).toBeVisible();
    expect(screen.queryByText("No clip analyzed yet")).not.toBeInTheDocument();
    expect(screen.queryByText("YOUR NEXT MOVE")).not.toBeInTheDocument();
    expect(
      fetcher.mock.calls.some(([, options]) => options?.method === "POST"),
    ).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Find a wing" }));
    expect(screen.getByLabelText("Scouting mission")).toHaveValue(
      "Find me an undervalued wing.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Run sample scan" }));
    await waitFor(() =>
      expect(fetcher).toHaveBeenCalledWith(
        "/api/scans",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            instruction: "Find me an undervalued wing.",
            league_id: "demo-nba",
          }),
        }),
      ),
    );
  });

  it("links report-only readiness directly to player availability without disabling scouting", async () => {
    mockApi(connected());
    render(<App />);
    expect(
      await screen.findByRole("button", { name: "Run scan" }),
    ).toBeEnabled();
    fireEvent.click(
      screen.getByRole("button", { name: "Review player availability" }),
    );
    expect(await screen.findByLabelText("Acquisition status")).toBeVisible();
    expect(screen.getByLabelText("Basketball mode")).not.toBeVisible();
    expect(
      screen.getByRole("button", { name: "Back to scouting" }),
    ).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Back to scouting" }));
    expect(screen.getByRole("button", { name: "Run scan" })).toBeEnabled();
  });

  it("explains missing film and takes users to the upload instead of a dead end", async () => {
    const data = connected();
    data.scan_readiness = {
      ...data.scan_readiness!,
      ready: false,
      candidates: [],
      blockers: ["Upload a permitted clip before scanning."],
    };
    mockApi(data);
    render(<App />);
    expect(
      await screen.findByRole("button", { name: "Run scan" }),
    ).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Add player film" }));
    expect(
      await screen.findByRole("combobox", { name: "Target player" }),
    ).toHaveValue("");
    expect(
      screen.getByRole("button", { name: "Process local clip" }),
    ).toBeDisabled();
  });

  it("sends missing statistics to one focused setup section", async () => {
    const data = connected();
    data.league.scouting_ready = false;
    data.scan_readiness = {
      ...data.scan_readiness!,
      ready: false,
      candidates: [],
      blockers: ["Recent game logs unavailable."],
    };
    mockApi(data);
    render(<App />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Set up league data" }),
    );
    expect(
      await screen.findByRole("button", { name: "Refresh game logs" }),
    ).toBeVisible();
    expect(screen.getByLabelText("Basketball mode")).not.toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: "Rules" }));
    expect(screen.getByLabelText("Basketball mode")).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Refresh game logs", hidden: true }),
    ).not.toBeVisible();
  });

  it("does not describe simulated models on a real league as live analysis", async () => {
    const data = connected();
    data.models_mode = "mock";
    data.scan_readiness = {
      ...data.scan_readiness!,
      ready: false,
      blockers: ["Real athletes require live models."],
    };
    mockApi(data);
    render(<App />);
    expect(
      await screen.findByText(
        "Your roster is connected. Live analysis is unavailable.",
      ),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Run scan" })).toBeDisabled();
    fireEvent.click(
      screen.getByRole("button", { name: "Open sample league options" }),
    );
    expect(screen.getByRole("dialog")).toBeVisible();
    expect(
      screen.getByRole("button", {
        name: /Continue with the sample NBA league/,
      }),
    ).toBeVisible();
  });

  it("shows named progress phases and preserves navigation while a scan is running", async () => {
    const running = {
      ...fixture.scan,
      stage: "TRACKING",
      progress: 45,
      result: null,
    } as Scan;
    mockApi(fixture.bootstrap as Bootstrap, [running]);
    render(<App />);
    await openSavedScan();
    const progress = await screen.findByRole("progressbar", {
      name: "Scouting progress",
    });
    await waitFor(() =>
      expect(progress).toHaveAttribute("aria-valuenow", "45"),
    );
    expect(screen.getByText("Check film").closest("li")).toHaveAttribute(
      "aria-current",
      "step",
    );
    expect(screen.queryByText("No clip analyzed yet")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "My roster" }));
    expect(screen.getByText("Fictional sample roster")).toBeVisible();
  });

  it("refreshes global readiness after uploading and gives a route back to scouting", async () => {
    const data = connected();
    data.league.available = data.league.available.slice(0, 1);
    data.league.available[0].recent = {
      ready: true,
      sample_size: 3,
      window_start: "2026-10-29",
      window_end: "2026-11-04",
      provider: "fixture",
      fetched_at: "2026-11-04",
      reasons: [],
      games: [],
    };
    const fetcher = mockApi(data);
    const refresh = vi.fn().mockResolvedValue(undefined);
    const done = vi.fn();
    render(
      <Library
        data={data}
        onError={vi.fn()}
        onToast={vi.fn()}
        onRefresh={refresh}
        onDone={done}
      />,
    );
    fireEvent.change(screen.getByLabelText("Target player"), {
      target: { value: data.league.available[0].id },
    });
    fireEvent.submit(
      screen
        .getByRole("button", { name: "Process local clip" })
        .closest("form")!,
    );
    expect(
      await screen.findByText(
        "Clip saved. Return to scouting to check readiness.",
      ),
    ).toBeVisible();
    expect(refresh).toHaveBeenCalledOnce();
    const upload = fetcher.mock.calls.find(
      ([url, options]) => url === "/api/clips" && options?.method === "POST",
    );
    expect((upload?.[1]?.body as FormData).get("player_id")).toBe(
      data.league.available[0].id,
    );
    fireEvent.click(screen.getByRole("button", { name: "Back to scouting" }));
    expect(done).toHaveBeenCalledOnce();
  });

  it("keeps film and the scan-wide decision in the redesigned detail pane with the audit collapsed", async () => {
    mockApi(fixture.bootstrap as Bootstrap, [fixture.scan as Scan]);
    render(<App />);
    await openSavedScan();
    const report = await screen.findByRole("region", {
      name: "Selected player report",
    });
    const move = screen.getByRole("heading", { name: "Scan recommendation" });
    const film = screen.getByLabelText(
      `Analyzed clip for ${fixture.scan.result.candidates[0].player.name}`,
    );
    expect(report).toContainElement(film);
    expect(report).toContainElement(move);
    expect(
      film.compareDocumentPosition(move) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      screen.getByText("Tracking & evidence details").closest("details"),
    ).not.toHaveAttribute("open");
    expect(screen.getByRole("link", { name: /Download PNG/ })).toBeVisible();
    expect(
      screen.queryByText("Find your next opportunity."),
    ).not.toBeInTheDocument();
  });
});

it("starts the automatic live workflow even when cached readiness needs refresh or film", async () => {
  const data = connected();
  data.scan_readiness = {
    ...data.scan_readiness!,
    ready: false,
    blockers: ["Old statistics and no uploaded clip."],
    candidates: [],
  };
  data.workflow = {
    automatic: true,
    can_start: true,
    blockers: [],
    footage_configured: false,
    footage_discovery_enabled: true,
    stats_updated_at: null,
    roster_updated_at: null,
  };
  mockApi(data);
  render(<App />);
  expect(
    await screen.findByRole("button", { name: "Run live scan" }),
  ).toBeEnabled();
  expect(
    screen.getByText("Your league is connected. Run a scan."),
  ).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "Set up league data" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Add player film" }),
  ).not.toBeInTheDocument();
});

it("explains a missing live service connection without offering simulated analysis", async () => {
  const data = connected();
  data.workflow = {
    automatic: true,
    can_start: false,
    blockers: [
      "Live analysis needs the model service key configured on this server.",
    ],
    footage_configured: false,
    footage_discovery_enabled: true,
    stats_updated_at: null,
    roster_updated_at: null,
  };
  mockApi(data);
  render(<App />);
  expect(
    await screen.findByRole("button", { name: "Run live scan" }),
  ).toBeDisabled();
  expect(
    screen.getByText(/Live analysis needs the model service key/),
  ).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "Run sample scan" }),
  ).not.toBeInTheDocument();
});

it("displays public viewing links without pretending that their footage was analyzed", async () => {
  const report = structuredClone(fixture.scan) as Scan;
  report.mode = "live";
  report.result!.staged_move = null;
  const candidate = report.result!.candidates[0];
  candidate.clip = null;
  candidate.verified = false;
  candidate.footage_sources = [
    {
      title: "A real publisher clip",
      url: "https://www.espn.com/video/clip/_/id/123",
      game_date: "2026-11-04",
      publisher: "ESPN",
      status: "viewing_link_only",
    },
  ];
  report.result!.candidates = [candidate];
  mockApi(connected(), [report]);
  render(<App />);
  await openSavedScan();
  expect(await screen.findByText(/No footage analyzed for/)).toBeVisible();
  expect(
    screen.getByRole("link", { name: /A real publisher clip/ }),
  ).toHaveAttribute("href", "https://www.espn.com/video/clip/_/id/123");
  expect(
    screen.getByText(
      "Viewing links only. These clips were not downloaded or analyzed.",
    ),
  ).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "Play clip" }),
  ).not.toBeInTheDocument();
});

it("shows the public clip's publisher, game date and excerpt provenance", async () => {
  const report = structuredClone(fixture.scan) as Scan;
  const clip = report.result!.candidates[0].clip!;
  clip.is_demo = false;
  clip.public_source = true;
  clip.source_ref = "https://www.espn.com/video/clip/_/id/123";
  clip.source_title = "Sam Hauser drills triple";
  clip.game_date = "2026-11-01";
  report.result!.candidates[0].tracking = null;
  mockApi(connected(), [report]);
  render(<App />);
  await openSavedScan();
  expect(await screen.findByText("Public ESPN highlight")).toBeVisible();
  expect(
    screen.getByRole("link", { name: "Sam Hauser drills triple" }),
  ).toHaveAttribute("href", clip.source_ref);
  expect(screen.getByText(/Game date: 2026-11-01/)).toBeVisible();
});

it("shows automatically collected clips before the optional upload flow", async () => {
  const data = connected();
  data.workflow = {
    automatic: true,
    can_start: true,
    blockers: [],
    footage_configured: true,
    footage_discovery_enabled: true,
    public_footage_analysis_enabled: true,
    stats_updated_at: null,
    roster_updated_at: null,
  };
  const clip = {
    ...fixture.scan.result!.candidates[0].clip!,
    public_source: true,
    source: "Public ESPN highlight",
    source_ref: "https://www.espn.com/video/clip/_/id/123",
    source_title: "Recent player highlight",
    game_date: "2026-11-01",
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, json: async () => [clip] })),
  );
  render(
    <Library
      data={data}
      onError={vi.fn()}
      onToast={vi.fn()}
      onRefresh={vi.fn().mockResolvedValue(undefined)}
      onDone={vi.fn()}
    />,
  );
  expect(
    await screen.findByRole("link", { name: /Recent player highlight/ }),
  ).toBeVisible();
  expect(screen.getByLabelText("Target player")).not.toBeVisible();
  fireEvent.click(screen.getByText("Add your own clip (optional)"));
  expect(screen.getByLabelText("Target player")).toBeVisible();
});

it("takes a failed automatic scan to the requested rules tab and retries its persisted scan", async () => {
  const failed = {
    ...fixture.scan,
    stage: "FAILED",
    result: null,
    error: "League rules need review.",
    action_needed: {
      destination: "data",
      section: "rules",
      label: "Review league data",
    },
  } as Scan;
  const fetcher = mockApi(connected(), [failed]);
  render(<App />);
  await openSavedScan();
  fireEvent.click(
    await screen.findByRole("button", { name: "Review league data" }),
  );
  expect(await screen.findByRole("tab", { name: "Rules" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  expect(screen.getByLabelText("Basketball mode")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Back to scouting" }));
  fireEvent.click(await screen.findByRole("button", { name: "Retry scan" }));
  await waitFor(() =>
    expect(fetcher).toHaveBeenCalledWith(
      `/api/scans/${failed.id}/retry`,
      expect.objectContaining({ method: "POST" }),
    ),
  );
});

it("keeps backend workflow blockers authoritative when cached scan readiness is true", async () => {
  const data = connected();
  data.workflow = {
    automatic: true,
    can_start: false,
    blockers: [
      "Automatic game-log refresh needs a statistics source configured on this server.",
    ],
    footage_configured: true,
    footage_discovery_enabled: true,
    stats_updated_at: null,
    roster_updated_at: null,
  };
  const fetcher = mockApi(data);
  render(<App />);
  const button = await screen.findByRole("button", { name: "Run live scan" });
  expect(button).toBeDisabled();
  fireEvent.submit(button.closest("form")!);
  expect(
    fetcher.mock.calls.some(([, options]) => options?.method === "POST"),
  ).toBe(false);
});
