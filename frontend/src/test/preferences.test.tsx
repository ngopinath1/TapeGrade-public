import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import App from "../pages/App";
import { Roster } from "../components/Roster";
import fixture from "./fixture.json";
import type { Bootstrap, Scan } from "../types";

describe("fresh workspaces and review counts", () => {
  it("opens fresh, counts only unread finished scans, and remembers reviewed reports on reopen", async () => {
    const saved = { ...structuredClone(fixture.scan), reviewed: false } as Scan;
    const running = {
      ...saved,
      id: "running",
      stage: "TRACKING",
      result: null,
    };
    const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
      if (url.endsWith("/review")) {
        saved.reviewed = true;
        return { ok: true, json: async () => ({ reviewed: true }) };
      }
      return {
        ok: true,
        json: async () =>
          url === "/api/bootstrap"
            ? fixture.bootstrap
            : url === "/api/scans"
              ? [saved, running]
              : saved,
      };
    });
    vi.stubGlobal("fetch", fetcher);
    const view = render(<App />);
    expect(
      await screen.findByText("Find your next opportunity."),
    ).toBeVisible();
    expect(screen.getByLabelText("1 unreviewed scan")).toBeVisible();
    expect(
      fetcher.mock.calls.some(([url]) => url === `/api/scans/${saved.id}`),
    ).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: /Scan history/ }));
    fireEvent.click(
      screen.getByRole("button", {
        name: new RegExp(saved.instruction + ".*Unreviewed"),
      }),
    );
    await screen.findByRole("heading", { name: saved.instruction });
    await waitFor(() =>
      expect(
        screen.queryByLabelText("1 unreviewed scan"),
      ).not.toBeInTheDocument(),
    );
    view.unmount();
    render(<App />);
    expect(
      await screen.findByText("Find your next opportunity."),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Scan history" })).toBeVisible();
  });

  it("keeps a review through stale history responses and temporary sync failures", async () => {
    const saved = {
      ...structuredClone(fixture.scan),
      id: "stale-history-review",
      reviewed: false,
    } as Scan;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => ({
        ok: !url.endsWith("/review"),
        json: async () =>
          url === "/api/bootstrap"
            ? fixture.bootstrap
            : url === "/api/scans"
              ? [structuredClone(saved)]
              : url.endsWith("/review")
                ? { detail: "Temporarily unavailable" }
                : saved,
      })),
    );
    const first = render(<App />);
    fireEvent.click(
      await screen.findByRole("button", { name: /Scan history/ }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: new RegExp(saved.instruction) }),
    );
    await screen.findByRole("heading", { name: saved.instruction });
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Scan history" }),
      ).toBeVisible(),
    );
    first.unmount();
    render(<App />);
    expect(
      await screen.findByRole("button", { name: "Scan history" }),
    ).toBeVisible();
    expect(
      screen.queryByLabelText("1 unreviewed scan"),
    ).not.toBeInTheDocument();
  });
});

it("saves decimal and negative scoring weights and retains them after navigating away", async () => {
  const data = structuredClone(fixture.bootstrap) as Bootstrap;
  data.league.scoring = {
    type: "points",
    weights: { pts: 1, reb: 1.2, ast: 1.5, stl: 3, blk: 3, to: -1 },
  };
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    if (url === "/api/settings" && options?.method === "PUT") {
      data.settings = JSON.parse(options.body as string);
      data.league.scoring!.weights = data.settings.scoring_weights!;
    }
    return {
      ok: true,
      json: async () =>
        url === "/api/bootstrap"
          ? data
          : url === "/api/scans"
            ? []
            : data.settings,
    };
  });
  vi.stubGlobal("fetch", fetcher);
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Guardrails" }));
  expect(
    screen.queryByRole("button", { name: "System" }),
  ).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Rebounds scoring weight"), {
    target: { value: "1.75" },
  });
  fireEvent.change(screen.getByLabelText("Turnovers scoring weight"), {
    target: { value: "" },
  });
  expect(screen.getByLabelText("Turnovers scoring weight")).toBeInvalid();
  fireEvent.change(screen.getByLabelText("Turnovers scoring weight"), {
    target: { value: "-2.5" },
  });
  fireEvent.submit(document.getElementById("guardrails-form")!);
  await screen.findByText(/Guardrails saved/);
  expect(data.settings.scoring_weights).toMatchObject({ reb: 1.75, to: -2.5 });
  fireEvent.click(screen.getByRole("button", { name: "My roster" }));
  fireEvent.click(screen.getByRole("button", { name: "Guardrails" }));
  expect(screen.getByLabelText("Rebounds scoring weight")).toHaveValue(1.75);
  expect(screen.getByLabelText("Turnovers scoring weight")).toHaveValue(-2.5);
});

it("explains roster trends and game counts on hover, focus and tap", () => {
  const data = structuredClone(fixture.bootstrap) as Bootstrap;
  data.league.is_demo = false;
  data.league.roster[0].recent = {
    ready: true,
    sample_size: 4,
    window_start: "2026-10-29",
    window_end: "2026-11-04",
    provider: "fixture",
    fetched_at: "2026-11-04",
    reasons: [],
    games: [],
  };
  render(<Roster data={data} />);
  expect(screen.getByText(/· 4 games/)).toBeVisible();
  const trend = screen.getByRole("button", {
    name: "About fantasy points trend",
  });
  fireEvent.mouseEnter(trend);
  expect(screen.getByRole("tooltip")).toHaveTextContent(
    "oldest on the left to newest on the right",
  );
  fireEvent.keyDown(window, { key: "Escape" });
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  const recent = screen.getByRole("button", {
    name: "About recent fantasy points per game",
  });
  fireEvent.focus(recent);
  expect(screen.getByRole("tooltip")).toHaveTextContent(
    "sample size used for this average",
  );
  fireEvent.blur(recent);
  fireEvent.click(trend);
  expect(screen.getByRole("tooltip")).toBeVisible();
});
