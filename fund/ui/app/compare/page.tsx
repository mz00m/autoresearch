export const dynamic = "force-dynamic";

export default function ComparePage() {
  return (
    <div className="space-y-10">
      <header>
        <div className="eyebrow">Counterfactual</div>
        <h1 className="font-serif text-4xl font-semibold tracking-tight mt-2">
          Strategy comparison
        </h1>
        <p className="text-sm text-muted mt-2 max-w-2xl">
          Side-by-side simulation of every bench strategy over the same window
          on real Yahoo data. Each run uses an isolated paper account — your
          live state is never touched. Generate fresh numbers from the terminal:
        </p>
      </header>

      <div className="card px-6 py-5 bg-rule/20">
        <h3 className="font-serif text-lg font-semibold">Run a fresh comparison</h3>
        <pre className="font-mono text-xs bg-paper border border-rule rounded p-3 mt-3 overflow-x-auto">
{`# 90 trading days ending today, all 7 strategies
python3 -m fund.compare --days 90

# specific window
python3 -m fund.compare --days 60 --end 2025-04-30

# only a subset
python3 -m fund.compare --strategies dual_momentum,adaptive,leveraged_momentum`}
        </pre>
        <p className="text-xs text-muted mt-3">
          Output writes to{" "}
          <code className="font-mono">fund/comparison.html</code> and prints a
          summary table to the terminal. The HTML has overlaid equity curves +
          a metrics table with the winner row highlighted.
        </p>
      </div>

      <div className="card px-6 py-5">
        <h3 className="font-serif text-lg font-semibold">
          Last live comparison (illustrative)
        </h3>
        <p className="text-xs text-muted mt-1">
          90 trading days ending 2025-04-30 · real Yahoo data · $25k paper
          accounts · 5bp slippage
        </p>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-[10px] uppercase tracking-eyebrow text-muted border-b border-rule">
              <tr>
                <th className="px-3 py-2 font-medium">Strategy</th>
                <th className="px-3 py-2 font-medium text-right">Cum</th>
                <th className="px-3 py-2 font-medium text-right">SPY</th>
                <th className="px-3 py-2 font-medium text-right">Excess</th>
                <th className="px-3 py-2 font-medium text-right">Max DD</th>
                <th className="px-3 py-2 font-medium text-right">End equity</th>
              </tr>
            </thead>
            <tbody>
              {[
                ["dual_momentum", 18.48, -5.57, 29619, true],
                ["top_n_momentum", 11.83, -7.21, 27957, false],
                ["adaptive", 7.33, -7.01, 26834, false],
                ["leveraged_momentum", 6.41, -12.30, 26603, false],
                ["risk_parity", 4.76, -6.08, 26191, false],
                ["sixty_forty", -1.54, -10.93, 24614, false],
                ["ma_crossover", -9.64, -18.60, 22589, false],
              ].map(([name, cum, dd, eq, winner]) => {
                const c = cum as number;
                const d = dd as number;
                const e = eq as number;
                const w = winner as boolean;
                return (
                  <tr
                    key={name as string}
                    className={`border-b border-rule/60 last:border-0 ${
                      w ? "bg-[#f3f6ee]" : ""
                    }`}
                  >
                    <td className="px-3 py-2.5">
                      <code className="font-mono text-xs">{name}</code>
                      {w && <span className="ml-2 tag tag-filled">Winner</span>}
                    </td>
                    <td className={`px-3 py-2.5 text-right num ${c >= 0 ? "text-ok" : "text-alert"}`}>
                      {c >= 0 ? "+" : ""}{c.toFixed(2)}%
                    </td>
                    <td className="px-3 py-2.5 text-right num text-muted">
                      -7.65%
                    </td>
                    <td className={`px-3 py-2.5 text-right num ${(c + 7.65) >= 0 ? "text-ok" : "text-alert"}`}>
                      {(c + 7.65) >= 0 ? "+" : ""}{(c + 7.65).toFixed(2)}pp
                    </td>
                    <td className="px-3 py-2.5 text-right num text-alert">
                      {d.toFixed(2)}%
                    </td>
                    <td className="px-3 py-2.5 text-right num">
                      ${e.toLocaleString()}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
