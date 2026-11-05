import { useCallback, useEffect, useState } from "react";
import { api, complete } from "../lib/api";
import type { Bootstrap, Scan } from "../types";
import { rememberReview, wasReviewed, withReview } from "../lib/scanReviews";

export function useDashboard() {
  const [data, setData] = useState<Bootstrap | null>(null);
  const [history, setHistory] = useState<Scan[]>([]);
  const [scan, setScan] = useState<Scan | null>(null);
  const [scanId, setScanId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const refresh = useCallback(async (resetWorkspace = false) => {
    try {
      const [bootstrap, scans] = await Promise.all([
        api<Bootstrap>("/bootstrap"),
        api<Scan[]>("/scans"),
      ]);
      setData(bootstrap);
      setHistory(scans.map((scan) => withReview(bootstrap.league.id, scan)));
      for (const scan of scans) {
        if (
          complete(scan.stage) &&
          scan.reviewed === false &&
          wasReviewed(bootstrap.league.id, scan)
        ) {
          void api(`/scans/${scan.id}/review`, { method: "POST" }).catch(
            () => {},
          );
        }
      }
      if (resetWorkspace) {
        setScan(null);
        setScanId(null);
        setError("");
      }
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  useEffect(() => {
    void refresh();
  }, [refresh]);
  useEffect(() => {
    if (!scanId) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await api<Scan>(`/scans/${scanId}`);
        if (!alive) return;
        setScan(data ? withReview(data.league.id, next) : next);
        if (!complete(next.stage)) timer = setTimeout(poll, 850);
        else void refresh();
      } catch (e) {
        if (alive) setError((e as Error).message);
      }
    };
    void poll();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [scanId, refresh, data?.league.id]);
  const run = async (instruction: string) => {
    setError("");
    try {
      const next = await api<{ id: string }>("/scans", {
        method: "POST",
        body: JSON.stringify({ instruction, league_id: data?.league.id }),
        headers: { "Idempotency-Key": crypto.randomUUID() },
      });
      setScan(null);
      setScanId(next.id);
      void refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const reloadScan = async () => {
    if (scanId && data)
      setScan(withReview(data.league.id, await api<Scan>(`/scans/${scanId}`)));
  };
  const markReviewed = useCallback(
    async (viewed: Scan) => {
      if (!data || !complete(viewed.stage)) return;
      rememberReview(data.league.id, viewed);
      const update = (item: Scan) => withReview(data.league.id, item);
      setHistory((items) => items.map(update));
      setScan((current) => current && update(current));
      try {
        await api<{ reviewed: boolean }>(`/scans/${viewed.id}/review`, {
          method: "POST",
        });
      } catch {
        // Review is saved locally; refresh retries server synchronization.
      }
    },
    [data?.league.id],
  );
  return {
    data,
    history,
    scan,
    scanId,
    error,
    setError,
    run,
    refresh,
    setScanId,
    reloadScan,
    markReviewed,
  };
}
