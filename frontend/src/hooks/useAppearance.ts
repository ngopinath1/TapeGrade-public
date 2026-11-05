import { useEffect, useState } from "react";

export type Appearance = "light" | "dark";
const storageKey = "tapegrade-appearance";

export function useAppearance() {
  const [appearance, setAppearance] = useState<Appearance>(() => {
    try {
      const saved = localStorage.getItem(storageKey);
      if (saved === "light" || saved === "dark") return saved;
    } catch {
      // Appearance still works when browser storage is unavailable.
    }
    return typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  });
  useEffect(() => {
    document.documentElement.dataset.appearance = appearance;
    try {
      localStorage.setItem(storageKey, appearance);
    } catch {
      // Keep the selection for this session.
    }
  }, [appearance]);
  return [appearance, setAppearance] as const;
}
