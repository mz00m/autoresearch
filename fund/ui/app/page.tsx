import { EquityChart } from "@/components/EquityChart";
import { HoldingsTable } from "@/components/HoldingsTable";
import { KpiRow } from "@/components/KpiRow";
import { SendOrdersButton } from "@/components/SendOrdersButton";
import { TicketsTable } from "@/components/TicketsTable";
import { VerdictCard } from "@/components/VerdictCard";
import {
  computeDecision,
  formatMoney,
  formatPct,
  readDailyLog,
  readPortfolio,
  readUiCache,
  type DriftSnapshot,
  type RegimeSnapshot,
  type TaxSummary,
  type Ticket,
} from "@/lib/data";

export const dynamic = "force-dynamic";

export default async function TodayPage() {
  const pf = await readPortfolio();
  const log = await readDailyLog();
  const cache = await readUiCache();
  const decision = computeDecision(log);

  if (!pf) {
    return (
      <div className="card px-8 py-16 text-center">
        <h1 className="font-serif text-2xl font-semibold">No paper portfolio yet</h1>
        <p className="text-muted mt-3 text-sm">Initialize one from the terminal:</p>
        <pre className="font-mono text-xs bg-rule/40 inline-block mt-4 px-4 py-2 rounded">
          python3 -m fund.portfolio init --principal 25000 --strategy top_n_momentum
        </pre>
      </div>
    );
  }

  const prices: Record<string, number> = {};
  if (cache?.prices) Object.assign(prices, cache.prices);
  for (const [sym, p] of Object.entries(pf.positions)) {
    if (!(sym in prices)) prices[sym] = p.avg_cost;
  }
  for (const t of pf.filled.slice().reverse()) {
    if (t.fill_price && !(t.symbol in cache?.prices ?? {})) {
      prices[t.symbol] = t.fill_price;
    }
  }

  const positionValue = Object.entries(pf.positions).reduce(
    (acc, [sym, p]) => acc + p.qty * (prices[sym] ?? p.avg_cost),
    0
  );
  const equity =
    pf.history.length > 0 ? pf.history[pf.history.length - 1].equity : pf.cash + positionValue;
  const cum = pf.principal > 0 ? equity / pf.principal - 1 : 0;
  const dayRet = log.length > 0 ? log[log.length - 1].day_return : 0;
  const peak = pf.history.reduce((m, h) => Math.max(m, h.equity), equity);
  const dd = peak > 0 ? (peak - equity) / peak : 0;

  const today = new Date().toISOString().slice(0, 10);
  const fillsToday: Ticket[] = pf.filled.filter((t) => t.fill_date === today);

  const base = pf.history[0]?.equity ?? pf.principal;
  const portCurve = pf.history.map((h) => ({
    date: h.date,
    portfolio: base > 0 ? h.equity / base - 1 : 0,
  }));
  const dateToBench = new Map(
    log.map((r) => [r.date, r.benchmark_cum_return ?? 0])
  );
  const chartRows = portCurve.map((p) => ({
    ...p,
    benchmark: dateToBench.get(p.date) ?? null,
  }));

  const strategyLabel =
    pf.active_strategy_params && Object.keys(pf.active_strategy_params).length > 0
      ? `${pf.active_strategy} · ${Object.entries(pf.active_strategy_params)
          .map(([k, v]) => `${k}=${v}`)
          .join(", ")}`
      : pf.active_strategy;

  const hasPending = pf.pending.length > 0;
  const washWarnings = Object.entries(cache?.tax_summary?.wash_sale_warnings ?? {});

  return (
    <div className="space-y-10">
      <header>
        <div className="eyebrow">Daily research note</div>
        <h1 className="font-serif text-4xl font-semibold tracking-tight mt-2">
          {new Date().toLocaleDateString("en-US", {
            weekday: "long",
            month: "long",
            day: "numeric",
            year: "numeric",
          })}
        </h1>
        <p className="text-sm text-muted mt-2">
          Active strategy <strong className="text-ink">{strategyLabel}</strong>{" "}
          · Inception {pf.inception || "—"} · Principal{" "}
          <span className="num">{formatMoney(pf.principal)}</span>
        </p>
      </header>

      <KpiRow
        kpis={[
          { label: "Equity", value: formatMoney(equity) },
          {
            label: "Today",
            value: formatPct(dayRet),
            tone: dayRet > 0 ? "pos" : dayRet < 0 ? "neg" : "default",
          },
          {
            label: "Since inception",
            value: formatPct(cum),
            tone: cum > 0 ? "pos" : cum < 0 ? "neg" : "default",
          },
          {
            label: "Drawdown",
            value: dd > 0 ? `-${(dd * 100).toFixed(2)}%` : "0.00%",
            tone: dd > 0 ? "neg" : "default",
          },
          { label: "Cash", value: formatMoney(pf.cash) },
        ]}
      />

      <VerdictCard decision={decision} />

      <section>
        <SectionHeading
          eyebrow="Action"
          title="Today's recommendations"
          help="Every BUY has cleared the risk engine + concentration + wash-sale checks."
        />
        <div className="mt-4 space-y-3">
          <SendOrdersButton hasPending={hasPending} />
          <TicketsTable
            tickets={pf.pending}
            emptyText="No tickets. The book is already at target — no action today."
          />
        </div>
      </section>

      {washWarnings.length > 0 && (
        <WashSaleWarnings warnings={washWarnings} />
      )}

      <div className="grid md:grid-cols-3 gap-4">
        {cache?.regime_snapshot && (
          <RegimeCard r={cache.regime_snapshot} />
        )}
        {cache?.tax_summary && (
          <TaxCard t={cache.tax_summary} />
        )}
        {cache?.drift_snapshot && (
          <DriftCard d={cache.drift_snapshot} />
        )}
      </div>

      <section>
        <SectionHeading eyebrow="Position" title="Holdings" />
        <div className="mt-4">
          <HoldingsTable positions={pf.positions} cash={pf.cash} prices={prices} />
        </div>
      </section>

      {fillsToday.length > 0 && (
        <section>
          <SectionHeading eyebrow="Closeout" title="Today's fills" />
          <div className="mt-4">
            <TicketsTable tickets={fillsToday} emptyText="No fills today." />
          </div>
        </section>
      )}

      <section>
        <SectionHeading eyebrow="Track record" title="Equity vs SPY benchmark" />
        <div className="mt-4">
          <EquityChart rows={chartRows} />
        </div>
      </section>

      <CacheFooter generatedAt={cache?.generated_at} />
    </div>
  );
}

function SectionHeading({
  eyebrow,
  title,
  help,
}: {
  eyebrow: string;
  title: string;
  help?: string;
}) {
  return (
    <div>
      <div className="eyebrow">{eyebrow}</div>
      <h2 className="font-serif text-2xl font-semibold mt-1.5">{title}</h2>
      {help && <p className="text-sm text-muted mt-1.5 max-w-2xl">{help}</p>}
    </div>
  );
}

const REGIME_TONE = {
  CALM: { border: "border-l-ok", text: "text-ok", label: "Calm" },
  NORMAL: { border: "border-l-accent", text: "text-accent", label: "Normal" },
  STRESSED: { border: "border-l-watch", text: "text-watch", label: "Stressed" },
  PANIC: { border: "border-l-alert", text: "text-alert", label: "Panic" },
  ERROR: { border: "border-l-muted", text: "text-muted", label: "Unavailable" },
} as const;

function RegimeCard({ r }: { r: RegimeSnapshot }) {
  const tone = REGIME_TONE[r.regime];
  return (
    <article className={`card border-l-4 ${tone.border} px-5 py-4`}>
      <div className="eyebrow">Macro regime</div>
      <div className={`font-serif text-xl font-semibold mt-1 ${tone.text}`}>
        {tone.label}
      </div>
      <p className="text-xs text-muted mt-2">
        VIX <strong className="num text-ink">{r.vix?.toFixed(1) ?? "—"}</strong>
        {" · "}10y−3mo{" "}
        <strong className="num text-ink">
          {r.curve_slope !== null && r.curve_slope !== undefined
            ? `${r.curve_slope > 0 ? "+" : ""}${r.curve_slope.toFixed(2)}`
            : "—"}
        </strong>
        {" · "}SPY{" "}
        <strong className="text-ink">
          {r.spy_above_200d === true
            ? "above 200d"
            : r.spy_above_200d === false
            ? "below 200d"
            : "—"}
        </strong>
      </p>
      {r.routed_to && (
        <p className="text-xs text-muted mt-2">
          → Routed to <code className="font-mono">{r.routed_to}</code>
        </p>
      )}
    </article>
  );
}

function TaxCard({ t }: { t: TaxSummary }) {
  return (
    <article className="card border-l-4 border-l-accent px-5 py-4">
      <div className="eyebrow">{t.year} realized P&amp;L (YTD)</div>
      <div
        className={`font-serif text-xl font-semibold mt-1 num ${
          t.net_total > 0 ? "text-ok" : t.net_total < 0 ? "text-alert" : ""
        }`}
      >
        {t.net_total >= 0 ? "+" : ""}
        {formatMoney(t.net_total)}
      </div>
      <div className="text-xs text-muted mt-2 grid grid-cols-2 gap-y-1">
        <span>Short-term net</span>
        <span className="num text-right text-ink">
          {t.net_short_term >= 0 ? "+" : ""}
          {formatMoney(t.net_short_term)}
        </span>
        <span>Long-term net</span>
        <span className="num text-right text-ink">
          {t.net_long_term >= 0 ? "+" : ""}
          {formatMoney(t.net_long_term)}
        </span>
        <span>Open tax lots</span>
        <span className="num text-right text-ink">{t.lot_count}</span>
      </div>
    </article>
  );
}

const DRIFT_TONE = {
  in_band: { border: "border-l-ok", text: "text-ok", label: "In band" },
  drifting: { border: "border-l-watch", text: "text-watch", label: "Drifting" },
  drifted: { border: "border-l-alert", text: "text-alert", label: "Drifted" },
} as const;

function DriftCard({ d }: { d: DriftSnapshot }) {
  const tone = DRIFT_TONE[d.verdict];
  return (
    <article className={`card border-l-4 ${tone.border} px-5 py-4`}>
      <div className="eyebrow">
        Live vs backtest · {d.n_live} live / {d.n_backtest} bt days
      </div>
      <div className={`font-serif text-xl font-semibold mt-1 ${tone.text}`}>
        {tone.label}
      </div>
      <p className="text-xs text-muted mt-2">
        Live <strong className="num text-ink">{(d.live_mean_annualized * 100).toFixed(1)}%/yr</strong>
        {" vs backtest "}
        <strong className="num text-ink">{(d.backtest_mean_annualized * 100).toFixed(1)}%/yr</strong>
        {" · t="}
        <strong className="num text-ink">{d.t_statistic.toFixed(2)}</strong>
      </p>
      <p className="text-[11px] text-muted mt-2 italic">{d.reason}</p>
    </article>
  );
}

function WashSaleWarnings({ warnings }: { warnings: [string, string][] }) {
  return (
    <article className="card border-l-4 border-l-watch px-5 py-4">
      <div className="eyebrow">Wash-sale tracking</div>
      <div className="font-serif text-lg font-semibold mt-1 text-watch">
        {warnings.length} symbol{warnings.length === 1 ? "" : "s"} in 30-day window
      </div>
      <p className="text-xs text-muted mt-1">
        BUYs in these symbols will be deferred to preserve the loss deduction
        (IRC §1091).
      </p>
      <ul className="text-xs text-ink mt-3 space-y-1">
        {warnings.map(([sym, soldOn]) => {
          const sold = new Date(soldOn);
          const elapsed = Math.floor(
            (Date.now() - sold.getTime()) / (24 * 3600 * 1000)
          );
          const remaining = Math.max(0, 30 - elapsed + 1);
          return (
            <li key={sym} className="font-sans">
              <strong className="font-mono">{sym}</strong>{" "}
              <span className="text-muted">
                sold at loss {soldOn} ({elapsed}d ago) · {remaining}d until clear
              </span>
            </li>
          );
        })}
      </ul>
    </article>
  );
}

function CacheFooter({ generatedAt }: { generatedAt?: string }) {
  if (!generatedAt) {
    return (
      <div className="text-xs text-muted font-sans">
        UI cache not generated yet — run{" "}
        <code className="font-mono bg-rule/40 px-1 rounded">
          python3 -m fund.cache_for_ui
        </code>{" "}
        to populate regime / tax / drift cards.
      </div>
    );
  }
  return (
    <div className="text-xs text-muted font-sans border-t border-rule pt-4">
      Cards on this page refreshed{" "}
      <strong className="text-ink">
        {new Date(generatedAt).toLocaleString()}
      </strong>{" "}
      — re-run{" "}
      <code className="font-mono bg-rule/40 px-1 rounded">
        python3 -m fund.cache_for_ui
      </code>{" "}
      to update.
    </div>
  );
}
