"use client";

import { useState } from "react";

type Preview = {
  exit_code: number;
  stderr: string;
  preview: {
    strategy?: string;
    params?: Record<string, unknown>;
    weights?: Record<string, number>;
    allocation?: Record<
      string,
      { weight: number; dollars: number; shares: number; price: number }
    >;
    prices?: Record<string, number>;
    error?: string;
  };
};

const STRATEGIES = [
  { id: "sixty_forty", label: "60/40 (SPY/AGG)", params: {} },
  { id: "dual_momentum", label: "Dual momentum (252d)", params: { lookback_days: 252 } },
  { id: "top_n_momentum", label: "Top-2 momentum (126d)", params: { n: 2, lookback_days: 126 } },
  { id: "risk_parity", label: "Risk parity (63d vol)", params: { vol_window: 63 } },
  { id: "ma_crossover", label: "MA crossover 50/200 SPY", params: { fast: 50, slow: 200 } },
  { id: "leveraged_momentum", label: "Leveraged momentum (3x ETFs)", params: { n: 2, lookback_days: 63 } },
  { id: "regime_aware", label: "Regime-aware (VIX + curve)", params: {} },
  { id: "adaptive", label: "Adaptive (trailing Sortino picker)", params: { lookback_days: 90 } },
  { id: "stable_adaptive", label: "Stable adaptive (persistence-gated)", params: {} },
  { id: "multi", label: "Multi (60% top-N + 40% risk-parity)", params: {} },
] as const;

export function StrategyPicker({
  currentStrategy,
  onSwitched,
}: {
  currentStrategy: string | null;
  onSwitched?: () => void;
}) {
  const [selected, setSelected] = useState<string>(
    currentStrategy ?? "top_n_momentum"
  );
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [switchMsg, setSwitchMsg] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);

  const spec = STRATEGIES.find((s) => s.id === selected) ?? STRATEGIES[0];

  const runPreview = async () => {
    setBusy(true);
    setSwitchMsg(null);
    try {
      const resp = await fetch("/api/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ strategy: spec.id, params: spec.params }),
      });
      setPreview(await resp.json());
    } catch (e: unknown) {
      setPreview({
        exit_code: -1,
        stderr: (e as Error).message,
        preview: { error: (e as Error).message },
      });
    } finally {
      setBusy(false);
    }
  };

  const runSwitch = async () => {
    setBusy(true);
    setSwitchMsg(null);
    try {
      const resp = await fetch("/api/switch-strategy", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ strategy: spec.id, params: spec.params }),
      });
      const data = await resp.json();
      setSwitchMsg(
        data.exit_code === 0
          ? `✓ ${data.stdout.trim()} — run Morning to generate rotation tickets`
          : `✗ exit ${data.exit_code}: ${data.stderr || data.stdout}`
      );
      onSwitched?.();
    } catch (e: unknown) {
      setSwitchMsg(`✗ ${(e as Error).message}`);
    } finally {
      setBusy(false);
      setConfirming(false);
    }
  };

  return (
    <article className="card px-5 py-4">
      <div className="eyebrow">Strategy</div>
      <h3 className="font-serif text-lg font-semibold mt-1">
        Switch active strategy or preview a candidate
      </h3>
      <div className="flex flex-wrap gap-3 items-center mt-3">
        <select
          value={selected}
          onChange={(e) => {
            setSelected(e.target.value);
            setPreview(null);
            setSwitchMsg(null);
          }}
          disabled={busy}
          className="px-3 py-1.5 rounded border border-rule bg-paper text-sm font-sans min-w-[280px]"
        >
          {STRATEGIES.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}
              {s.id === currentStrategy ? "  (active)" : ""}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={runPreview}
          disabled={busy}
          className="px-3 py-1.5 rounded border border-rule text-sm font-sans bg-paper hover:bg-rule/30 disabled:opacity-50"
        >
          {busy && !confirming ? "Computing…" : "Preview"}
        </button>
        {selected !== currentStrategy && (
          !confirming ? (
            <button
              type="button"
              onClick={() => setConfirming(true)}
              disabled={busy}
              className="px-3 py-1.5 rounded text-sm font-sans font-semibold bg-accent text-white hover:opacity-90 disabled:opacity-50"
            >
              Switch active to {spec.id}
            </button>
          ) : (
            <>
              <button
                type="button"
                onClick={runSwitch}
                disabled={busy}
                className="px-3 py-1.5 rounded text-sm font-sans font-semibold bg-watch text-white hover:opacity-90 disabled:opacity-50"
              >
                Confirm switch
              </button>
              <button
                type="button"
                onClick={() => setConfirming(false)}
                disabled={busy}
                className="px-2 py-1 text-sm font-sans text-muted hover:text-ink"
              >
                Cancel
              </button>
            </>
          )
        )}
      </div>
      {switchMsg && (
        <p
          className={`mt-3 text-sm ${
            switchMsg.startsWith("✓") ? "text-ok" : "text-alert"
          }`}
        >
          {switchMsg}
        </p>
      )}
      {preview && <PreviewPanel preview={preview} />}
    </article>
  );
}

function PreviewPanel({ preview }: { preview: Preview }) {
  const p = preview.preview;
  if (p.error) {
    return (
      <div className="mt-3 p-3 rounded bg-[#fdefef] border border-alert/30 text-alert text-sm font-mono">
        {p.error}
      </div>
    );
  }
  const rows = Object.entries(p.allocation ?? {}).filter(
    ([sym, a]) => sym !== "__cash_residual__" && (a.shares > 0 || a.weight > 0)
  );
  const residual = (p.allocation?.__cash_residual__?.dollars ?? 0);
  return (
    <div className="mt-4 border-t border-rule pt-4">
      <div className="text-[10px] uppercase tracking-eyebrow text-muted font-sans">
        Preview · {p.strategy} {p.params ? JSON.stringify(p.params) : ""}
      </div>
      {rows.length === 0 ? (
        <p className="text-sm text-muted italic mt-2">
          All cash — no signal cleared the T-bill gate.
        </p>
      ) : (
        <table className="w-full text-sm mt-2 font-sans">
          <thead>
            <tr className="text-[10px] uppercase tracking-eyebrow text-muted border-b border-rule">
              <th className="text-left py-1">Symbol</th>
              <th className="text-right py-1">Weight</th>
              <th className="text-right py-1">Shares</th>
              <th className="text-right py-1">@ price</th>
              <th className="text-right py-1">Notional</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([sym, a]) => (
              <tr key={sym} className="border-b border-rule/40">
                <td className="py-1.5 font-medium">{sym}</td>
                <td className="py-1.5 text-right num">
                  {(a.weight * 100).toFixed(1)}%
                </td>
                <td className="py-1.5 text-right num">{a.shares}</td>
                <td className="py-1.5 text-right num">${a.price.toFixed(2)}</td>
                <td className="py-1.5 text-right num">
                  ${(a.shares * a.price).toLocaleString(undefined, {
                    maximumFractionDigits: 0,
                  })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {residual > 0.01 && (
        <p className="text-[11px] text-muted mt-2 font-sans">
          Cash residual after share rounding: ${residual.toFixed(2)}
        </p>
      )}
    </div>
  );
}
