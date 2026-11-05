import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { FilmPlayer } from "../components/FilmPlayer";
import fixture from "./fixture.json";
import type { Candidate } from "../types";

it("does not list basketball or defenders in the legend when only the target was tracked", () => {
  const candidate = structuredClone(
    fixture.scan.result.candidates[0],
  ) as Candidate;
  candidate.tracking!.frames.forEach((frame) => {
    frame.objects = frame.objects.filter((o) => o.role === "target");
  });
  render(<FilmPlayer candidate={candidate} />);
  expect(screen.getByText("Target player")).toBeVisible();
  expect(
    screen.queryByText("Basketball", { exact: true }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByText("Defenders", { exact: true }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByText(/No confirmed defender tracks · Basketball not tracked/),
  ).toBeVisible();
});

it("shows reviewed anonymous players without labeling them as the target or defenders", () => {
  const candidate = structuredClone(
    fixture.scan.result.candidates[0],
  ) as Candidate;
  candidate.verified = false;
  candidate.tracking_accepted = false;
  candidate.reviewed_tracking = structuredClone(candidate.tracking!);
  candidate.reviewed_tracking.frames.forEach((frame) => {
    frame.objects = frame.objects
      .filter((o) => o.role !== "ball")
      .map((o) => ({ ...o, role: "unknown" }));
  });
  candidate.tracking_review = {
    scene_only: true,
    quality_by_id: {},
    trusted_object_ids: [1, 2, 3],
    target_quality: 0,
    issues: [],
    roles: { target: 0, defender: 0, ball: 0, unknown: 3 },
  };
  render(<FilmPlayer candidate={candidate} />);
  expect(screen.getByText("Unidentified players")).toBeVisible();
  expect(
    screen.getByText(/Visible players are tracked without names/),
  ).toBeVisible();
  expect(
    screen.getByLabelText("Segmentation and bounding box overlay"),
  ).toBeVisible();
  expect(
    screen.queryByText("Target player", { exact: true }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByText("Defenders", { exact: true }),
  ).not.toBeInTheDocument();
});
