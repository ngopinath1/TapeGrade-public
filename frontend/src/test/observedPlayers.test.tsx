import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { IdentifiedPlayers } from "../components/IdentifiedPlayers";
import type { ObservedPlayerProfile } from "../types";

function profile(name = "Fixture Player"): ObservedPlayerProfile {
  return {
    id: name,
    object_id: 1,
    name,
    team: "BOS",
    jersey_number: "30",
    espn_id: "123",
    stats_player_id: "fixture",
    league_player_id: "sleeper:fixture",
    availability: "available",
    roster_source: "https://example.test/roster",
    game_date: "2026-11-01",
    match_status: "matched",
    statistics: {
      ready: true,
      fresh: true,
      synthetic: true,
      provider: "fixture",
      fetched_at: "2026-11-04T17:00:00Z",
      window_start: "2026-10-29",
      window_end: "2026-11-04",
      sample_size: 3,
      fantasy_per_game: 12.5,
      minutes_per_game: 20,
      averages: {
        pts: { value: 10, sample_size: 3 },
        reb: { value: 0, sample_size: 3 },
      },
      games: [
        {
          date: "2026-11-01",
          minutes: 20,
          score: 12.5,
          stats: { pts: 10, reb: 0 },
          source_ref: "cache:stats/fixture/abc.json",
        },
      ],
      reasons: [],
    },
    film: {
      quality: 0,
      accepted: false,
      identity_continuity_confirmed: false,
      notice: "Needs review",
      metrics: [],
    },
    recommendation: {
      verdict: "MONITOR",
      rationale: "More reliable tape is needed.",
      source: "evidence_gate",
    },
  };
}

describe("identified player performance", () => {
  it("keeps each player's numbers, membership and recommendation separate", () => {
    const other = profile("Other Fixture");
    other.availability = "rostered_elsewhere";
    other.statistics!.fantasy_per_game = 25;
    other.recommendation = {
      verdict: "TRADE_RESEARCH",
      rationale: "Rostered elsewhere.",
      source: "evidence_gate",
    };
    render(<IdentifiedPlayers profiles={[profile(), other]} />);
    const first = within(
      screen.getByRole("article", { name: "Fixture Player performance" }),
    );
    const second = within(
      screen.getByRole("article", { name: "Other Fixture performance" }),
    );
    expect(first.getByText("12.5", { selector: "strong" })).toBeVisible();
    expect(first.getByText("Unrostered in your league")).toBeVisible();
    expect(first.getByText("Player continuity not confirmed")).toBeVisible();
    expect(second.getByText("25")).toBeVisible();
    expect(second.getByText("Trade research")).toBeVisible();
    expect(second.getByText("On another team's roster")).toBeVisible();
    expect(first.getByText("0", { selector: "dd" })).toBeVisible();
  });
  it("opens the dated roster and exact saved game source while preserving missing stats", () => {
    render(<IdentifiedPlayers profiles={[profile()]} />);
    fireEvent.click(screen.getByText("Game logs and identity sources"));
    expect(screen.getByRole("link", { name: /Game roster/ })).toHaveAttribute(
      "href",
      "https://example.test/roster",
    );
    expect(
      screen.getByRole("link", {
        name: "Fixture Player source box score 2026-11-01",
      }),
    ).toHaveAttribute("href", "/media/cache/stats/fixture/abc.json");
    const table = within(screen.getByRole("table"));
    expect(table.getByRole("cell", { name: "—" })).toBeVisible();
    expect(table.getByRole("cell", { name: "0" })).toBeVisible();
  });
  it("does not fabricate statistics for an unverified join", () => {
    const p = profile();
    p.statistics = null;
    p.availability = "unknown";
    p.recommendation = {
      verdict: "MORE_DATA",
      rationale: "Verify the statistics join.",
      source: "evidence_gate",
    };
    render(<IdentifiedPlayers profiles={[p]} />);
    expect(screen.getByText("More data needed")).toBeVisible();
    expect(screen.getByText(/No numbers were inferred/)).toBeVisible();
    expect(screen.queryByText("Fantasy pts/game")).not.toBeInTheDocument();
    expect(screen.queryByText("12.5")).not.toBeInTheDocument();
  });
});
