import type { Scan } from "../types";

const key = (leagueId: string) => `tapegrade-reviewed-scans:${leagueId}`;
const signature = (scan: Scan) => `${scan.attempts}:${scan.stage}`;
const memory = new Map<string, Record<string, string>>();

function read(leagueId: string): Record<string, string> {
  try {
    const saved = JSON.parse(localStorage.getItem(key(leagueId)) ?? "{}");
    if (saved && typeof saved === "object" && !Array.isArray(saved)) {
      memory.set(leagueId, { ...saved, ...memory.get(leagueId) });
    }
  } catch {
    /* Retain reviews for this session if storage is unavailable. */
  }
  return memory.get(leagueId) ?? {};
}

export function wasReviewed(leagueId: string, scan: Scan) {
  return read(leagueId)[scan.id] === signature(scan);
}

export function rememberReview(leagueId: string, scan: Scan) {
  const saved = { ...read(leagueId), [scan.id]: signature(scan) };
  memory.set(leagueId, saved);
  try {
    localStorage.setItem(key(leagueId), JSON.stringify(saved));
  } catch {
    /* Session fallback above. */
  }
}

export function withReview(leagueId: string, scan: Scan): Scan {
  // Older APIs did not record reviews; do not turn every legacy report into a new alert.
  return {
    ...scan,
    reviewed: (scan.reviewed ?? true) || wasReviewed(leagueId, scan),
  };
}
