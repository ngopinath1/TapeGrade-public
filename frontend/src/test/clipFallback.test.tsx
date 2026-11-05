import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ClipAttempts } from "../components/ClipAttempts";
import { ScanProgress } from "../components/ScanProgress";
import fixture from "./fixture.json";
import type { Candidate, Scan } from "../types";

function candidate(): Candidate {
  const c = structuredClone(fixture.scan.result.candidates[0]) as Candidate;
  c.clip_fallback = {
    limit: 2,
    attempted: 2,
    tried_alternative: true,
    selected_clip_id: "second",
    stop_reason: "usable_clip",
    notice:
      "Automatically switched footage and used clip 2 after an earlier clip was unclear.",
  };
  c.clip_attempts = [
    {
      number: 1,
      clip_id: "first",
      source_ref: "https://example.test/first",
      source_title: "First source",
      game_date: null,
      quality: 0.4,
      outcome: "tracking_unclear",
      reason: "Player track drifted.",
      selected: false,
    },
    {
      number: 2,
      clip_id: "second",
      source_ref: "https://example.test/second",
      source_title: "Second source",
      game_date: null,
      quality: 0.9,
      outcome: "usable",
      reason: "Identity and tracking accepted.",
      selected: true,
    },
  ];
  return c;
}
describe("automatic clip fallback", () => {
  it("labels non-overlapping excerpts as views of the same play", () => {
    const c = candidate();
    c.clip_fallback!.same_highlight_excerpts = true;
    c.clip_attempts![0].source_span = { start: 0, end: 5 };
    c.clip_attempts![1].source_span = { start: 11, end: 16 };
    render(<ClipAttempts candidate={c} />);
    expect(
      screen.getByText(/same play, not independent game samples/),
    ).toBeVisible();
    expect(screen.getByText("Automatically checked 2 excerpts")).toBeVisible();
    fireEvent.click(screen.getByText("See clip checks"));
    expect(screen.getByText("Source excerpt: 11.0–16.0s")).toBeVisible();
  });
  it("explains the automatic switch, keeps the first rejection and identifies the selected source", () => {
    render(<ClipAttempts candidate={candidate()} />);
    expect(screen.getByText("Automatically checked 2 clips")).toBeVisible();
    fireEvent.click(screen.getByText("See clip checks"));
    expect(screen.getByText("Player track drifted.")).toBeVisible();
    expect(screen.getByText("Clip 2 · Shown in this report")).toBeVisible();
    expect(screen.getByRole("link", { name: "Second source" })).toHaveAttribute(
      "href",
      "https://example.test/second",
    );
  });
  it("explains a preserved call limit without implying that an alternative was analyzed", () => {
    const c = candidate();
    c.clip_fallback = {
      ...c.clip_fallback!,
      attempted: 1,
      tried_alternative: false,
      stop_reason: "budget_limit",
      notice: "The remaining call budget is reserved for the final report.",
    };
    c.clip_attempts = c.clip_attempts!.slice(0, 1);
    render(<ClipAttempts candidate={c} />);
    expect(screen.getByText(/remaining call budget/)).toBeVisible();
    expect(
      screen.queryByText(/Automatically checked 2/),
    ).not.toBeInTheDocument();
  });
  it("keeps the active progress in Check film while switching clips", () => {
    const s = {
      ...fixture.scan,
      stage: "SWITCHING_CLIPS",
      events: [
        {
          id: 123,
          created_at: "",
          stage: "SWITCHING_CLIPS",
          actor: "TapeGrade",
          message:
            "The first clip was unclear. Automatically checking a different clip.",
          detail: {},
        },
      ],
    } as Scan;
    render(<ScanProgress scan={s} />);
    expect(
      screen.getByRole("heading", {
        name: /Automatically checking a different clip/,
      }),
    ).toBeVisible();
    expect(screen.getByText("Check film").closest("li")).toHaveAttribute(
      "aria-current",
      "step",
    );
  });
});
