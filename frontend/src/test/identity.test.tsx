import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PlayerIdentity } from "../components/PlayerIdentity";
import { FilmPlayer } from "../components/FilmPlayer";
import fixture from "./fixture.json";
import type { Candidate } from "../types";

function candidate(): Candidate {
  const data = structuredClone(fixture.scan.result.candidates[0]) as Candidate;
  data.identity = {
    version: 2,
    status: "corroborated",
    expected_name: "Sam Hauser",
    expected_team: "BOS",
    expected_jersey: "30",
    source_ref: "https://www.espn.com/nba/boxscore/_/gameId/401909903",
    source_date: "2026-11-01",
    method: "Roster, visible jersey, continuity",
    reasons: [],
    continuity_frames: [0, 12],
    evidence: [
      {
        frame: 0,
        time: 0,
        jersey_number: "30",
        team: "BOS",
        crop_url: "/media/cache/identity/proof.jpg",
        source_url: "/media/cache/frames/0.jpg",
        evidence: "Visible white jersey 30",
      },
    ],
    tracked_players: [
      {
        object_id: 1,
        role: "target",
        name: "Sam Hauser",
        team: "BOS",
        jersey_number: "30",
        status: "roster_and_jersey_match",
      },
      {
        object_id: 2,
        role: "defender",
        name: null,
        team: "ORL",
        jersey_number: null,
        status: "unidentified",
      },
    ],
  };
  return data;
}

describe("player identity evidence", () => {
  it("shows jersey proof and its original frame, dated roster, and an unnamed unreadable opponent", () => {
    render(<PlayerIdentity candidate={candidate()} />);
    expect(screen.getByText("Identity corroborated")).toBeVisible();
    expect(
      screen.getByRole("link", { name: /Check the game roster/ }),
    ).toHaveAttribute(
      "href",
      "https://www.espn.com/nba/boxscore/_/gameId/401909903",
    );
    const proof = screen.getByAltText("Jersey 30 evidence at 0.0 seconds");
    expect(proof.closest("a")).toHaveAttribute(
      "href",
      "/media/cache/frames/0.jpg",
    );
    fireEvent.click(screen.getByText("Player names and tracking IDs"));
    expect(screen.getByText(/Unidentified player/)).toBeVisible();
    expect(screen.getByText(/Sam Hauser/, { selector: "li" })).toBeVisible();
  });

  it.each(["unconfirmed", "tracking_rejected"] as const)(
    "withholds names for %s evidence",
    (status) => {
      const data = candidate();
      data.identity!.status = status;
      data.identity!.reasons = ["Visible jersey evidence conflicts."];
      render(<PlayerIdentity candidate={data} />);
      fireEvent.click(screen.getByText("Player names and tracking IDs"));
      expect(
        screen.queryByText(/Sam Hauser/, { selector: "li" }),
      ).not.toBeInTheDocument();
      expect(
        screen.getByText("Visible jersey evidence conflicts."),
      ).toBeVisible();
      expect(screen.getAllByText(/Identity not confirmed/)).toHaveLength(2);
    },
  );

  it("hides unreliable tracks initially and labels inspection without resolved names", () => {
    const data = candidate();
    data.quality = 0.45;
    data.tracking_accepted = false;
    data.tracking!.simulated = false;
    data.tracking!.frames[0].objects[0].id = 1;
    render(<FilmPlayer candidate={data} />);
    const toggle = screen.getByRole("button", {
      name: "Toggle segmentation overlays",
    });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(
      screen.queryByLabelText("Segmentation and bounding box overlay"),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Film measurements were withheld",
    );
    fireEvent.click(toggle);
    const overlay = screen.getByLabelText(
      "Segmentation and bounding box overlay",
    );
    expect(overlay).not.toHaveTextContent("Sam Hauser");
    expect(
      screen.getByText("UNRELIABLE TRACKS · FOR INSPECTION"),
    ).toBeVisible();
  });
});
