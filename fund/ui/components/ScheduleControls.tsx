"use client";

import { useEffect, useState } from "react";

type Job = {
  name: string;
  time: string;
  description: string;
  last_success: string | null;
  last_run: string | null;
  last_exit: number | null;
};

type ScheduleData = {
  jobs: Job[];
  installed: boolean;
  log_tail: string[];
};

export function ScheduleControls() {
  const [data, setData] = useState<ScheduleData | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const load = async () => {
    try {
      const r = await fetch("/api/schedule-status", { cache: "no-store" });
      setData(await r.json());
    } catch (e: unknown) {
      setMsg(`load failed: ${(e as Error).message}`);
    }
  };

  useEffect(() => { load(); }, []);

  const act = async (action: "install" | "uninstall" | "once") => {
    setBusy(action);
    setMsg(null);
    try {
      const r = await fetch("/api/schedule-status", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      const out = await r.json();
      setMsg(
        out.exit_code === 0
          ? `✓ ${action}: ${(out.stdout || "").trim().split("\n").slice(-3).join(" — ")}`
          : `✗ ${action} exit ${out.exit_code}: ${(out.stderr || out.stdout || "").slice(0, 200)}`
      );
      await load();
    } catch (e: unknown) {
      setMsg(`✗ ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  };

  if (!data) {
    return <div className="card px-6 py-8 text-muted italic">Loading…</div>;
  }

  return (
    <>
      <article className="card px-5 py-4">
        <div className="flex items-baseline justify-between gap-4">
          <div>
            <div className="eyebrow">launchd agent (macOS)</div>
            <div className={`font-serif text-xl font-semibold mt-1 ${
              data.installed ? "text-ok" : "text-muted"
            }`}>
              {data.installed ? "Installed — running in background" : "Not installed"}
            </div>
            <p className="text-sm text-muted mt-1">
              {data.installed
                ? "Survives logout and reboot. Polls every 60s to check whether any job is due."
                : "Without this, jobs only run when you click 'Run once' or the dashboard is open."}
            </p>
          </div>
          <div className="flex flex-col gap-2">
            {!data.installed ? (
              <button
                type="button"
                disabled={busy !== null}
                onClick={() => act("install")}
                className="px-4 py-1.5 rounded text-sm font-sans font-semibold bg-accent text-white hover:opacity-90 disabled:opacity-50"
              >
                {busy === "install" ? "Installing…" : "Install agent"}
              </button>
            ) : (
              <button
                type="button"
                disabled={busy !== null}
                onClick={() => act("uninstall")}
                className="px-4 py-1.5 rounded text-sm font-sans border border-alert text-alert hover:bg-alert/10 disabled:opacity-50"
              >
                {busy === "uninstall" ? "Removing…" : "Uninstall"}
              </button>
            )}
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => act("once")}
              className="px-4 py-1.5 rounded text-sm font-sans border border-rule hover:bg-rule/30 disabled:opacity-50"
            >
              {busy === "once" ? "Running…" : "Run due jobs once"}
            </button>
          </div>
        </div>
        {msg && (
          <p className={`mt-3 text-sm font-mono ${msg.startsWith("✓") ? "text-ok" : "text-alert"}`}>
            {msg}
          </p>
        )}
      </article>

      <section>
        <h2 className="font-serif text-2xl font-semibold mb-4">Daily schedule</h2>
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="text-left text-[10px] uppercase tracking-eyebrow text-muted border-b border-rule">
              <tr>
                <th className="px-4 py-3 font-medium">Time (ET)</th>
                <th className="px-4 py-3 font-medium">Job</th>
                <th className="px-4 py-3 font-medium">Description</th>
                <th className="px-4 py-3 font-medium">Last success</th>
                <th className="px-4 py-3 font-medium text-right">Exit</th>
              </tr>
            </thead>
            <tbody>
              {data.jobs.map((j) => (
                <tr key={j.name} className="border-b border-rule/60 last:border-0">
                  <td className="px-4 py-3 num font-mono">{j.time}</td>
                  <td className="px-4 py-3 font-mono text-xs">{j.name}</td>
                  <td className="px-4 py-3 text-ink/80">{j.description}</td>
                  <td className="px-4 py-3 num text-muted">
                    {j.last_success ?? "—"}
                  </td>
                  <td
                    className={`px-4 py-3 num text-right ${
                      j.last_exit === 0
                        ? "text-ok"
                        : j.last_exit !== null
                        ? "text-alert"
                        : "text-muted"
                    }`}
                  >
                    {j.last_exit ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h2 className="font-serif text-2xl font-semibold mb-4">Recent log</h2>
        {data.log_tail.length === 0 ? (
          <div className="card px-6 py-8 text-muted italic">
            No log yet — log appears after the first job fires.
          </div>
        ) : (
          <pre className="card p-4 text-[11px] font-mono whitespace-pre-wrap overflow-x-auto max-h-80">
            {data.log_tail.join("\n")}
          </pre>
        )}
      </section>

      <section className="card border-l-4 border-l-watch bg-[#fbf5e6] px-5 py-4">
        <div className="eyebrow">Stays manual</div>
        <p className="text-sm mt-2">
          <strong>Send orders</strong> and <strong>Cancel orders</strong> are
          deliberately not on this schedule. Sending BUYs commits cash to new
          positions, cancelling pulls capital back — both touch the broker
          irreversibly. Per <code className="font-mono">fund.md §7</code>, those
          stay one human click each.
        </p>
      </section>
    </>
  );
}
