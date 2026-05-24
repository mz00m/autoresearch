"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

type Action = "morning" | "closeout" | "refresh-cache";

const ACTIONS: { id: Action; label: string; help: string; endpoint: string }[] = [
  {
    id: "morning",
    label: "Run morning",
    help: "Generate today's pending tickets from the active strategy.",
    endpoint: "/api/morning",
  },
  {
    id: "closeout",
    label: "Run closeout",
    help: "Fill pending tickets at today's close, mark to market, append a daily-log row.",
    endpoint: "/api/closeout",
  },
  {
    id: "refresh-cache",
    label: "Refresh cards",
    help: "Recompute recommendations + tax + regime + drift cards.",
    endpoint: "/api/refresh-cache",
  },
];

type RunResult = {
  exit_code: number;
  stdout: string;
  stderr: string;
  command: string;
};

export function ActionBar() {
  const router = useRouter();
  const [busy, setBusy] = useState<Action | null>(null);
  const [last, setLast] = useState<{ action: Action; result: RunResult } | null>(null);

  const run = async (a: typeof ACTIONS[number]) => {
    setBusy(a.id);
    setLast(null);
    try {
      const resp = await fetch(a.endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source: "auto" }),
      });
      const data = (await resp.json()) as RunResult;
      setLast({ action: a.id, result: data });
      // Auto-refresh server components so the page reflects the new state
      if (data.exit_code === 0) router.refresh();
    } catch (e: unknown) {
      setLast({
        action: a.id,
        result: {
          exit_code: -1,
          stdout: "",
          stderr: (e as Error).message,
          command: "",
        },
      });
    } finally {
      setBusy(null);
    }
  };

  return (
    <article className="card px-5 py-4">
      <div className="eyebrow">Run</div>
      <h3 className="font-serif text-lg font-semibold mt-1">
        Daily operations
      </h3>
      <p className="text-sm text-muted mt-1">
        Replaces the terminal commands. Each click reloads the page
        afterward so the cards update.
      </p>
      <div className="flex flex-wrap gap-2 mt-3">
        {ACTIONS.map((a) => (
          <button
            key={a.id}
            type="button"
            onClick={() => run(a)}
            disabled={busy !== null}
            title={a.help}
            className="px-3 py-1.5 rounded border border-rule text-sm font-sans bg-paper hover:bg-rule/30 disabled:opacity-50"
          >
            {busy === a.id ? "Running…" : a.label}
          </button>
        ))}
        <button
          type="button"
          onClick={() => location.reload()}
          disabled={busy !== null}
          className="px-3 py-1.5 rounded text-sm font-sans text-muted hover:text-ink disabled:opacity-50"
        >
          Reload page
        </button>
      </div>
      {last && (
        <div
          className={`mt-3 p-3 rounded font-mono text-xs whitespace-pre-wrap border ${
            last.result.exit_code === 0
              ? "bg-[#f3f6ee] border-ok/30 text-ink"
              : "bg-[#fdefef] border-alert/30 text-alert"
          }`}
        >
          <strong className="font-sans not-italic">{last.action}</strong> · exit{" "}
          {last.result.exit_code}
          {"\n\n"}
          {last.result.stdout || "(no stdout)"}
          {last.result.stderr ? `\n\nSTDERR:\n${last.result.stderr}` : ""}
        </div>
      )}
    </article>
  );
}
