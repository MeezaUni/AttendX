import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorText } from "./api";

/** Load JSON from the API; optional polling interval (ms). */
export function useApi<T>(url: string | null, pollMs?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(Boolean(url));
  const urlRef = useRef(url);
  urlRef.current = url;

  const reload = useCallback(async () => {
    const u = urlRef.current;
    if (!u) return;
    try {
      const d = await api.get<T>(u);
      if (urlRef.current === u) {
        setData(d);
        setError(null);
      }
    } catch (e) {
      if (urlRef.current === u) setError(errorText(e));
    } finally {
      if (urlRef.current === u) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!url) return;
    setLoading(true);
    void reload();
    if (!pollMs) return;
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") void reload();
    }, pollMs);
    return () => window.clearInterval(id);
  }, [url, pollMs, reload]);

  return { data, error, loading, reload, setData };
}

export function fmtTime(iso: string | null | undefined, withDate = false): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return withDate
    ? d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })
    : d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

export function fmtDate(isoDate: string): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
}

export const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

export function download(url: string) {
  const a = document.createElement("a");
  a.href = url;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
}
