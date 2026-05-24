"use client";

import { useEffect, useState } from "react";

type Status = {
  running: boolean;
  pid?: number;
  started_at?: string;
  expires_at?: string;
  remaining_seconds?: number;
};

function _fmt(seconds: number): string {
  if (seconds <= 0) return "0m";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

export function KeepAwakeToggle() {
  const [status, setStatus] = useState<Status | null>(null);
  const [hours, setHours] = useState<number>(24);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      const r = await fetch("/api/keep-awake", { cache: "no-store" });
      const data = await r.json();
      setStatus(data.result);
    } catch {
      setStatus(null);
    }
  };

  useEffect(() => {
    load();
    // Refresh remaining time every 30s so the user sees the countdown
    const t = setInterval(load, 30_000);
    return () => clearInterval(t);
  }, []);

  const act = async (action: "start" | "stop") => {
    setBusy(true);
    try {
      await fetch("/api/keep-awake", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, hours }),
      });
      await load();
    } finally {
      setBusy(false);
    }
  };

  const running = status?.running ?? false;

  return (
    <article
      className={`card border-l-4 px-5 py-4 ${
        running ? "border-l-ok bg-[#f3f6ee]" : "border-l-muted"
      }`}
    >
      <div className="flex items-baseline justify-between gap-4 flex-wrap">
        <div>
          <div className="eyebrow">Mac sleep prevention</div>
          <div
            className={`font-serif text-xl font-semibold mt-1 ${
              running ? "text-ok" : "text-muted"
            }`}
          >
            {running ? "Awake (caffeinate running)" : "Sleep allowed"}
          </div>
          <p className="text-sm text-muted mt-1">
            {running
              ? `Mac will not sleep for the next ${_fmt(status?.remaining_seconds ?? 0)} (auto-expires ${
                  status?.expires_at?.replace("T", " ") ?? ""
                }). Pulls the plug on caffeinate cleanly when the timer hits.`
              : "Without this, macOS may sleep overnight even when plugged in — and your scheduled jobs would miss until you open the lid. Turn on before you walk away."}
          </p>
        </div>
        <div className="flex gap-2 items-center">
          {!running && (
            <>
              <label className="text-xs text-muted font-sans">hours</label>
              <input
                type="number"
                min={1}
                max={72}
                value={hours}
                onChange={(e) => setHours(Number(e.target.value) || 24)}
                disabled={busy}
                className="w-16 px-2 py-1 rounded border border-rule text-sm font-mono"
              />
              <button
                type="button"
                onClick={() => act("start")}
                disabled={busy}
                className="px-4 py-1.5 rounded text-sm font-sans font-semibold bg-accent text-white hover:opacity-90 disabled:opacity-50"
              >
                {busy ? "Starting…" : `Keep awake ${hours}h`}
              </button>
            </>
          )}
          {running && (
            <button
              type="button"
              onClick={() => act("stop")}
              disabled={busy}
              className="px-4 py-1.5 rounded text-sm font-sans border border-alert text-alert hover:bg-alert/10 disabled:opacity-50"
            >
              {busy ? "Stopping…" : "Let it sleep"}
            </button>
          )}
        </div>
      </div>
    </article>
  );
}
