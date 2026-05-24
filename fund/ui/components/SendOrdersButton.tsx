"use client";

import { useState } from "react";

type Result = {
  exit_code?: number;
  stdout?: string;
  stderr?: string;
  dry_run?: boolean;
  error?: string;
};

export function SendOrdersButton({
  hasPending,
}: {
  hasPending: boolean;
}) {
  const [broker, setBroker] = useState<"alpaca" | "ibkr">("alpaca");
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [result, setResult] = useState<Result | null>(null);

  if (!hasPending) {
    return (
      <div className="card px-5 py-4 text-sm text-muted bg-rule/10">
        No pending tickets to send.{" "}
        <code className="font-mono text-xs">python3 -m fund.morning</code>{" "}
        first to generate today's recommendations.
      </div>
    );
  }

  const run = async (dryRun: boolean) => {
    setBusy(true);
    setResult(null);
    try {
      const resp = await fetch("/api/send-orders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ broker, dryRun }),
      });
      const data = (await resp.json()) as Result;
      setResult(data);
    } catch (e: unknown) {
      setResult({ error: (e as Error).message });
    } finally {
      setBusy(false);
      setConfirming(false);
    }
  };

  return (
    <div className="card px-5 py-4 space-y-3">
      <div className="flex items-center gap-4 flex-wrap">
        <span className="text-sm font-medium">Send today's pending tickets to:</span>
        <select
          value={broker}
          onChange={(e) => setBroker(e.target.value as "alpaca" | "ibkr")}
          disabled={busy}
          className="px-3 py-1.5 rounded border border-rule bg-paper text-sm font-sans"
        >
          <option value="alpaca">Alpaca (paper)</option>
          <option value="ibkr">IBKR (IB Gateway required)</option>
        </select>
        <button
          type="button"
          onClick={() => run(true)}
          disabled={busy}
          className="px-3 py-1.5 rounded border border-rule text-sm font-sans bg-paper hover:bg-rule/30 disabled:opacity-50"
        >
          {busy ? "Running…" : "Dry-run"}
        </button>
        {!confirming ? (
          <button
            type="button"
            onClick={() => setConfirming(true)}
            disabled={busy}
            className="px-4 py-1.5 rounded text-sm font-sans font-semibold bg-accent text-white hover:opacity-90 disabled:opacity-50"
          >
            Send orders…
          </button>
        ) : (
          <>
            <button
              type="button"
              onClick={() => run(false)}
              disabled={busy}
              className="px-4 py-1.5 rounded text-sm font-sans font-semibold bg-alert text-white hover:opacity-90 disabled:opacity-50"
            >
              {busy ? "Sending…" : `Confirm — send to ${broker}`}
            </button>
            <button
              type="button"
              onClick={() => setConfirming(false)}
              disabled={busy}
              className="px-3 py-1.5 rounded text-sm font-sans text-muted hover:text-ink"
            >
              Cancel
            </button>
          </>
        )}
      </div>
      <p className="text-[11px] text-muted">
        Risk engine has already vetted every ticket. The broker is a dumb wire;
        it cannot resize or add an order on its own.
      </p>
      {result && (
        <div
          className={`mt-2 p-3 rounded font-mono text-xs whitespace-pre-wrap border ${
            result.error || (result.exit_code ?? 0) !== 0
              ? "bg-[#fdefef] border-alert/30 text-alert"
              : "bg-[#f3f6ee] border-ok/30 text-ink"
          }`}
        >
          {result.error
            ? `ERROR: ${result.error}`
            : `exit=${result.exit_code} ${result.dry_run ? "(dry-run)" : ""}\n\n${
                result.stdout || "(no stdout)"
              }${result.stderr ? `\n\nSTDERR:\n${result.stderr}` : ""}`}
        </div>
      )}
    </div>
  );
}
