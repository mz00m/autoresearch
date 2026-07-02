import { formatMoney, readUiCache, type SellSignal } from "@/lib/data";

export const dynamic = "force-dynamic";

const TONE = {
  HOLD: { border: "border-l-ok", tag: "bg-ok text-white" },
  WATCH: { border: "border-l-watch", tag: "bg-watch text-white" },
  SELL: { border: "border-l-alert", tag: "bg-alert text-white" },
} as const;

export default async function SellGuidePage() {
  const cache = await readUiCache();
  if (!cache) {
    return (
      <div className="card px-8 py-16 text-center">
        <h1 className="font-serif text-2xl font-semibold">No cached state</h1>
        <p className="text-muted mt-3 text-sm">Run:</p>
        <pre className="font-mono text-xs bg-rule/40 inline-block mt-4 px-4 py-2 rounded">
          python3 -m fund.cache_for_ui
        </pre>
      </div>
    );
  }
  const signals = cache.sell_signals;
  return (
    <div className="space-y-10">
      <header>
        <div className="eyebrow">When to sell</div>
        <h1 className="font-serif text-4xl font-semibold tracking-tight mt-2">
          Sell guide — {new Date(cache.as_of).toLocaleDateString("en-US",
            { weekday: "long", month: "long", day: "numeric", year: "numeric" })}
        </h1>
        <p className="text-sm text-muted mt-2">
          Strategy: <strong>{cache.active_strategy ?? "—"}</strong> ·{" "}
          {signals.length} open position{signals.length !== 1 ? "s" : ""}. Set
          broker-side stops at the printed prices; watch the strategy-exit
          line between morning runs.
        </p>
        <p className="text-[11px] text-muted mt-1 font-sans">
          Cache generated {new Date(cache.generated_at).toLocaleString()}
        </p>
      </header>

      {signals.length === 0 ? (
        <div className="card px-8 py-12 text-center text-muted italic">
          No open positions — nothing to manage.
        </div>
      ) : (
        <div className="space-y-4">
          {signals.map((s) => (
            <Card key={s.symbol} s={s} />
          ))}
        </div>
      )}
    </div>
  );
}

function Card({ s }: { s: SellSignal }) {
  const tone = TONE[s.action];
  const pnlClass = s.pnl_pct > 0 ? "text-ok" : s.pnl_pct < 0 ? "text-alert" : "";
  const stopPctFromHere = s.last > 0 ? (s.stop_loss_price / s.last - 1) * 100 : 0;
  const trailPctFromHere = s.last > 0 ? (s.trailing_stop_price / s.last - 1) * 100 : 0;
  return (
    <article className={`card border-l-4 ${tone.border} px-6 py-5`}>
      <div className="flex items-baseline justify-between">
        <div>
          <h2 className="font-sans text-2xl font-semibold tracking-tight">
            {s.symbol}{" "}
            <span className="text-sm font-normal text-muted ml-1">
              {s.qty} shares · {formatMoney(s.qty * s.last)}
            </span>
          </h2>
        </div>
        <span
          className={`tag ${tone.tag} text-[10px] px-3 py-1 rounded-sm font-semibold`}
        >
          {s.action}
        </span>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-4 pt-4 border-t border-rule">
        <div>
          <div className="kpi-label">Cost</div>
          <div className="num text-base mt-0.5">{formatMoney(s.cost)}</div>
        </div>
        <div>
          <div className="kpi-label">Last</div>
          <div className="num text-base mt-0.5">{formatMoney(s.last)}</div>
        </div>
        <div>
          <div className="kpi-label">P&amp;L</div>
          <div className={`num text-base mt-0.5 ${pnlClass}`}>
            {(s.pnl_pct * 100).toFixed(2)}%
          </div>
        </div>
        <div>
          <div className="kpi-label">Stop / Trail</div>
          <div className="num text-base mt-0.5">
            {formatMoney(s.stop_loss_price)} /{" "}
            {formatMoney(s.trailing_stop_price)}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-4">
        <div className="bg-paper border border-rule rounded p-3">
          <div className="kpi-label">Stop-loss order</div>
          <div className="text-sm mt-1">
            Set GTC stop at <strong className="num">{formatMoney(s.stop_loss_price)}</strong>
            <span className="text-muted ml-1">
              ({stopPctFromHere.toFixed(1)}% from here)
            </span>
          </div>
        </div>
        <div className="bg-paper border border-rule rounded p-3">
          <div className="kpi-label">Trailing stop</div>
          <div className="text-sm mt-1">
            Trail 15% below peak: today{" "}
            <strong className="num">{formatMoney(s.trailing_stop_price)}</strong>
            <span className="text-muted ml-1">
              ({trailPctFromHere.toFixed(1)}% from here)
            </span>
          </div>
        </div>
      </div>

      <div className="mt-4 p-3 bg-rule/20 rounded text-sm">
        <span className="kpi-label">Strategy exit</span>
        <p className="mt-1 text-ink/80">{s.strategy_exit}</p>
      </div>

      {s.reasons.length > 0 && (
        <ul className="mt-3 text-xs text-muted list-disc pl-5 space-y-0.5">
          {s.reasons.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      )}
    </article>
  );
}
