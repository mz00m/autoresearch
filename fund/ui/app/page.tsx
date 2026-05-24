import { EquityChart } from "@/components/EquityChart";
import { HoldingsTable } from "@/components/HoldingsTable";
import { KpiRow } from "@/components/KpiRow";
import { TicketsTable } from "@/components/TicketsTable";
import { VerdictCard } from "@/components/VerdictCard";
import {
  computeDecision,
  formatMoney,
  formatPct,
  readDailyLog,
  readPortfolio,
  type Ticket,
} from "@/lib/data";

export const dynamic = "force-dynamic";

export default async function TodayPage() {
  const pf = await readPortfolio();
  const log = await readDailyLog();
  const decision = computeDecision(log);

  if (!pf) {
    return (
      <div className="card px-8 py-16 text-center">
        <h1 className="font-serif text-2xl font-semibold">No paper portfolio yet</h1>
        <p className="text-muted mt-3 text-sm">
          Initialize one from the terminal:
        </p>
        <pre className="font-mono text-xs bg-rule/40 inline-block mt-4 px-4 py-2 rounded">
          python3 -m fund.portfolio init --principal 25000 --strategy sixty_forty
        </pre>
      </div>
    );
  }

  // Reference prices for mark-to-market: prefer the most recent fill, fall
  // back to avg_cost. (The Python morning/closeout writes the latest close
  // into history; we don't have per-symbol "last close" in state without
  // re-fetching, so we trust apply_fill's avg_cost as a recent proxy.)
  const prices: Record<string, number> = {};
  for (const [sym, p] of Object.entries(pf.positions)) {
    prices[sym] = p.avg_cost;
  }
  for (const t of pf.filled.slice().reverse()) {
    if (t.fill_price && !(t.symbol in prices && prices[t.symbol] !== 0)) {
      prices[t.symbol] = t.fill_price;
    }
  }
  for (const t of pf.pending) {
    if (t.ref_price && !(t.symbol in prices && prices[t.symbol] !== 0)) {
      prices[t.symbol] = t.ref_price;
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

  // Equity chart series (anchor at history[0] as 0%)
  const base = pf.history[0]?.equity ?? pf.principal;
  const portCurve = pf.history.map((h) => ({
    date: h.date,
    portfolio: base > 0 ? h.equity / base - 1 : 0,
  }));
  // SPY benchmark from daily log (already cumulative)
  const dateToBench = new Map(
    log.map((r) => [r.date, r.benchmark_cum_return ?? 0])
  );
  const chartRows = portCurve.map((p) => ({
    ...p,
    benchmark: dateToBench.get(p.date) ?? null,
  }));

  const strategyLabel = pf.active_strategy_params && Object.keys(pf.active_strategy_params).length > 0
    ? `${pf.active_strategy} · ${Object.entries(pf.active_strategy_params).map(([k, v]) => `${k}=${v}`).join(", ")}`
    : pf.active_strategy;

  return (
    <div className="space-y-12">
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
          help="What to send to the broker, in priority order. Every BUY has cleared the risk engine. SELLs only require ownership."
        />
        <div className="mt-4">
          <TicketsTable
            tickets={pf.pending}
            emptyText="No tickets. The book is already at target — no action today."
          />
        </div>
      </section>

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
