"use client";

import { useEffect, useState } from "react";

type Thesis = {
  symbol: string;
  catalyst: string;
  kill_switch: string;
  horizon: string;
  confidence: number;
  created_at: string;
  author: string;
  status: "active" | "invalidated" | "expired";
  invalidated_at?: string;
  invalidated_reason?: string;
};

export function ThesisPanel({ heldSymbols }: { heldSymbols: string[] }) {
  const [theses, setTheses] = useState<Thesis[]>([]);
  const [adding, setAdding] = useState<string | null>(null);
  const [form, setForm] = useState({
    catalyst: "", killSwitch: "", horizon: "", confidence: 3,
  });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const load = async () => {
    try {
      const r = await fetch("/api/thesis", { cache: "no-store" });
      const d = await r.json();
      setTheses(d.theses ?? []);
    } catch {}
  };

  useEffect(() => { load(); }, []);

  const activeFor = (sym: string): Thesis | null => {
    const actives = theses
      .filter((t) => t.symbol === sym && t.status === "active")
      .sort((a, b) => b.created_at.localeCompare(a.created_at));
    return actives[0] ?? null;
  };

  const missing = heldSymbols.filter((s) => !activeFor(s));

  const submit = async (symbol: string) => {
    setBusy(true);
    setMsg(null);
    try {
      const r = await fetch("/api/thesis", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol, ...form }),
      });
      const d = await r.json();
      if (d.error) {
        setMsg(`✗ ${d.error}`);
      } else {
        setMsg(`✓ thesis added for ${symbol}`);
        setAdding(null);
        setForm({ catalyst: "", killSwitch: "", horizon: "", confidence: 3 });
        await load();
      }
    } catch (e: unknown) {
      setMsg(`✗ ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  const invalidate = async (symbol: string) => {
    const reason = window.prompt(`Why is the ${symbol} thesis broken?`);
    if (!reason) return;
    setBusy(true);
    try {
      await fetch("/api/thesis", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "invalidate", symbol, reason }),
      });
      setMsg(`✗ ${symbol} thesis invalidated`);
      await load();
    } finally {
      setBusy(false);
    }
  };

  return (
    <article className="card border-l-4 border-l-accent px-5 py-4 space-y-3">
      <div className="flex items-baseline justify-between">
        <div>
          <div className="eyebrow">Thesis</div>
          <h3 className="font-serif text-lg font-semibold mt-1">
            Why are these positions held?
          </h3>
          <p className="text-xs text-muted mt-1 max-w-xl">
            Math identifies what would have survived noise. A thesis says what
            you believe about the world. When the thesis breaks, exit
            regardless of momentum.
          </p>
        </div>
      </div>
      {msg && (
        <p className={`text-sm ${msg.startsWith("✓") ? "text-ok" : "text-alert"}`}>
          {msg}
        </p>
      )}
      {heldSymbols.length === 0 ? (
        <p className="text-sm text-muted italic">
          No positions yet — once Tuesday fills land, write a thesis for each.
        </p>
      ) : (
        <div className="space-y-3">
          {heldSymbols.map((sym) => {
            const t = activeFor(sym);
            if (t) return <ThesisRow key={sym} t={t} onInvalidate={() => invalidate(sym)} />;
            return (
              <div key={sym} className="border-l-2 border-watch pl-3 py-2">
                <div className="flex items-center justify-between">
                  <div>
                    <strong className="font-mono">{sym}</strong>
                    <span className="text-watch text-xs ml-2 font-sans">no thesis attached</span>
                  </div>
                  {adding !== sym ? (
                    <button
                      type="button"
                      onClick={() => setAdding(sym)}
                      className="text-xs px-2 py-1 rounded border border-rule font-sans hover:bg-rule/30"
                    >
                      add thesis
                    </button>
                  ) : (
                    <button
                      type="button"
                      onClick={() => setAdding(null)}
                      className="text-xs px-2 py-1 text-muted font-sans"
                    >
                      cancel
                    </button>
                  )}
                </div>
                {adding === sym && (
                  <div className="mt-3 space-y-2 font-sans">
                    <input
                      type="text"
                      value={form.catalyst}
                      onChange={(e) => setForm({ ...form, catalyst: e.target.value })}
                      placeholder="Catalyst — why will this asset outperform?"
                      className="w-full px-2 py-1.5 text-sm rounded border border-rule"
                    />
                    <input
                      type="text"
                      value={form.killSwitch}
                      onChange={(e) => setForm({ ...form, killSwitch: e.target.value })}
                      placeholder="Kill switch — what would invalidate the thesis?"
                      className="w-full px-2 py-1.5 text-sm rounded border border-rule"
                    />
                    <div className="flex gap-2">
                      <input
                        type="text"
                        value={form.horizon}
                        onChange={(e) => setForm({ ...form, horizon: e.target.value })}
                        placeholder="Horizon (3-6mo, Q3 OPEC, etc)"
                        className="flex-1 px-2 py-1.5 text-sm rounded border border-rule"
                      />
                      <select
                        value={form.confidence}
                        onChange={(e) => setForm({ ...form, confidence: Number(e.target.value) })}
                        className="px-2 py-1.5 text-sm rounded border border-rule"
                      >
                        {[1, 2, 3, 4, 5].map((c) => (
                          <option key={c} value={c}>conviction {c}/5</option>
                        ))}
                      </select>
                      <button
                        type="button"
                        onClick={() => submit(sym)}
                        disabled={busy || !form.catalyst || !form.killSwitch || !form.horizon}
                        className="px-3 py-1.5 text-sm rounded bg-accent text-white font-semibold disabled:opacity-50"
                      >
                        Save
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
          {missing.length > 0 && (
            <p className="text-xs text-watch font-sans">
              {missing.length} position{missing.length !== 1 ? "s" : ""} without a thesis. Add one each — the system can\'t protect a trade whose rationale is undocumented.
            </p>
          )}
        </div>
      )}
    </article>
  );
}

function ThesisRow({ t, onInvalidate }: { t: Thesis; onInvalidate: () => void }) {
  return (
    <div className="border-l-2 border-ok pl-3 py-2">
      <div className="flex items-baseline justify-between">
        <div>
          <strong className="font-mono">{t.symbol}</strong>
          <span className="text-xs ml-2 text-muted font-sans">
            conviction {t.confidence}/5 · {t.horizon} · added {t.created_at.slice(0, 10)}
          </span>
        </div>
        <button
          type="button"
          onClick={onInvalidate}
          className="text-xs px-2 py-1 text-alert font-sans hover:bg-alert/10 rounded"
        >
          invalidate
        </button>
      </div>
      <p className="text-sm text-ink/80 mt-1">
        <strong>Catalyst:</strong> {t.catalyst}
      </p>
      <p className="text-sm text-muted mt-1">
        <strong className="text-ink/70">Kills if:</strong> {t.kill_switch}
      </p>
    </div>
  );
}
