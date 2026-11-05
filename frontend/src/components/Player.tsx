import { initials } from "../lib/api";
import type { Player } from "../types";
export function Sparkline({
  values,
  muted = false,
  label = "Seven-game sample trend",
}: {
  values: number[];
  muted?: boolean;
  label?: string;
}) {
  if (values.length < 2) return <span className="muted">Unavailable</span>;
  const min = Math.min(...values) - 2,
    max = Math.max(...values) + 2;
  const pts = values
    .map(
      (v, i) =>
        `${(i / (values.length - 1)) * 72},${25 - ((v - min) / (max - min)) * 22}`,
    )
    .join(" ");
  return (
    <svg width="74" height="28" viewBox="0 0 74 28" aria-label={label}>
      <polyline
        points={pts}
        fill="none"
        stroke={muted ? "var(--muted)" : "var(--success)"}
        strokeWidth="1.8"
      />
    </svg>
  );
}

export function Avatar({
  player,
  small = false,
}: {
  player: Player;
  small?: boolean;
}) {
  return (
    <span
      className={`avatar ${small ? "small" : ""} tone-${player.id.slice(-1)}`}
    >
      {initials(player.name)}
    </span>
  );
}

export function VerdictBadge({ value }: { value: string }) {
  return (
    <span className={`verdict verdict-${value.toLowerCase()}`}>{value}</span>
  );
}
