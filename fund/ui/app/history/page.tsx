import { EquityChart } from "@/components/EquityChart";
import { KpiRow } from "@/components/KpiRow";
import {
  formatMoney,
  formatPct,
  formatPp,
  readDailyLog,
  readPortfolio,
} from "@/lib/data";

export const dynamic = "force-dynamic";

export default async function HistoryPage() {
  const pf = await readPortfolio();
  const log = await readDailyLog();

  if (!pf || log.length === 0) {
    return (
      <div className="card px-8 py-16 text-center">
        <h1 className="font-serif text-2xl font-semibold">No history yet</h1>
        <p className="text-muted mt-3 text-sm">
          Run a closeout (or the simulator) to populate the daily log.
        </p>
      </div>
    );
  }

  const base = pf.history[0]?.equity ?? pf.principal;
  const dateToBench = new Map(
    log.map((r) => [r.date, r.benchmark_cum_return ?? 0])
  );
  const chartRows = pf.history.map((h) => ({
    date: h.date,
    portfolio: base > 0 ? h.equity / base - 1 : 0,
    benchmark: dateToBench.get(h.date) ?? null,
  }));

  const cum = log[log.length - 1].cum_return;
  const bench = log[log.length - 1].benchmark_cum_return ?? 0;
  const excess = cum - bench;
  const peakDD = log.reduce((m, r) => Math.max(m, r.drawdown), 0);
  const winningDays = log.filter((r) => r.day_return > 0).length;
  const hitRate = log.length > 0 ? winningDays / log.length : 0;

  return (
    <div className="space-y-12">
      <header>
        <div className="eyebrow">History</div>
        <h1 className="font-serif text-4xl font-semibold tracking-tight mt-2">
          Track record
        </h1>
        <p className="text-sm text-muted mt-2">
          {log.length} sessions logged since {log[0].date}.
        </p>
      </header>

      <KpiRow
        kpis={[
          {
            label: "Cumulative",
            value: formatPct(cum),
            tone: cum > 0 ? "pos" : cum < 0 ? "neg" : "default",
          },
          { label: "SPY same window", value: formatPct(bench), tone: "muted" },
          {
            label: "Excess",
            value: formatPp(excess),
            tone: excess > 0 ? "pos" : excess < 0 ? "neg" : "default",
          },
          {
            label: "Max drawdown",
            value: `-${(peakDD * 100).toFixed(2)}%`,
            tone: "neg",
          },
          { label: "Up days", value: `${(hitRate * 100).toFixed(0)}%` },
        ]}
      />

      <section>
        <h2 className="font-serif text-2xl font-semibold mb-4">Equity vs SPY</h2>
        <EquityChart rows={chartRows} />
      </section>

      <section>
        <h2 className="font-serif text-2xl font-semibold mb-4">Daily log</h2>
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="text-left text-[10px] uppercase tracking-eyebrow text-muted border-b border-rule">
              <tr>
                <th className="px-4 py-3 font-medium">Date</th>
                <th className="px-4 py-3 font-medium text-right">Day</th>
                <th className="px-4 py-3 font-medium text-right">Cum</th>
                <th className="px-4 py-3 font-medium text-right">SPY</th>
                <th className="px-4 py-3 font-medium text-right">Excess</th>
                <th className="px-4 py-3 font-medium text-right">DD</th>
                <th className="px-4 py-3 font-medium text-right">Equity</th>
                <th className="px-4 py-3 font-medium text-right">Fills</th>
              </tr>
            </thead>
            <tbody>
              {log
                .slice()
                .reverse()
                .map((r) => {
                  const excessRow = r.cum_return - (r.benchmark_cum_return ?? 0);
                  return (
                    <tr
                      key={r.date}
                      className="border-b border-rule/60 last:border-0 text-xs"
                    >
                      <td className="px-4 py-2.5 num">{r.date}</td>
                      <td
                        className={`px-4 py-2.5 text-right num ${
                          r.day_return > 0
                            ? "text-ok"
                            : r.day_return < 0
                            ? "text-alert"
                            : ""
                        }`}
                      >
                        {formatPct(r.day_return)}
                      </td>
                      <td className="px-4 py-2.5 text-right num">
                        {formatPct(r.cum_return)}
                      </td>
                      <td className="px-4 py-2.5 text-right num text-muted">
                        {r.benchmark_cum_return !== null
                          ? formatPct(r.benchmark_cum_return)
                          : "—"}
                      </td>
                      <td
                        className={`px-4 py-2.5 text-right num ${
                          excessRow > 0
                            ? "text-ok"
                            : excessRow < 0
                            ? "text-alert"
                            : ""
                        }`}
                      >
                        {formatPp(excessRow)}
                      </td>
                      <td className="px-4 py-2.5 text-right num text-alert">
                        {r.drawdown > 0
                          ? `-${(r.drawdown * 100).toFixed(2)}%`
                          : "0.00%"}
                      </td>
                      <td className="px-4 py-2.5 text-right num">
                        {formatMoney(r.equity)}
                      </td>
                      <td className="px-4 py-2.5 text-right num text-muted">
                        {r.n_filled}
                      </td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
