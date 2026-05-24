import { formatMoney, readUiCache, type UiCache } from "@/lib/data";

export const dynamic = "force-dynamic";

export default async function RecommendationsPage() {
  const cache = await readUiCache();
  if (!cache) {
    return <Empty />;
  }
  return (
    <div className="space-y-10">
      <header>
        <div className="eyebrow">If you traded today</div>
        <h1 className="font-serif text-4xl font-semibold tracking-tight mt-2">
          {new Date(cache.as_of).toLocaleDateString("en-US", {
            weekday: "long",
            month: "long",
            day: "numeric",
            year: "numeric",
          })}
        </h1>
        <p className="text-sm text-muted mt-2">
          Side-by-side recommendation from every strategy for principal{" "}
          <span className="num">{formatMoney(cache.principal)}</span>. Read-only —
          no tickets created. Active strategy is{" "}
          <strong>{cache.active_strategy ?? "—"}</strong>.
        </p>
        <p className="text-[11px] text-muted mt-1 font-sans">
          Cache generated {new Date(cache.generated_at).toLocaleString()} ·
          refresh with{" "}
          <code className="bg-rule/40 px-1 rounded">
            python3 -m fund.cache_for_ui
          </code>
        </p>
      </header>

      <div className="grid gap-4">
        {Object.entries(cache.recommendations).map(([name, info]) => (
          <StrategyCard
            key={name}
            name={name}
            info={info}
            active={name === cache.active_strategy}
            principal={cache.principal}
          />
        ))}
      </div>
    </div>
  );
}

function StrategyCard({
  name,
  info,
  active,
  principal,
}: {
  name: string;
  info: UiCache["recommendations"][string];
  active: boolean;
  principal: number;
}) {
  const allocation = info.allocation ?? {};
  const rows = Object.entries(allocation)
    .filter(([sym, a]) => sym !== "__cash_residual__" && (a.shares > 0 || a.weight > 0))
    .sort((a, b) => b[1].weight - a[1].weight);
  const residual = (allocation.__cash_residual__?.dollars ?? 0);
  return (
    <article
      className={`card px-6 py-5 ${active ? "border-accent border-2" : ""}`}
    >
      <div className="flex items-baseline justify-between">
        <div className="flex items-baseline gap-3">
          <h2 className="font-serif text-xl font-semibold">{name}</h2>
          {active && <span className="tag tag-filled">Active</span>}
        </div>
      </div>
      {info.error ? (
        <p className="text-sm text-alert mt-2 italic">{info.error}</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-muted mt-2 italic">
          All cash — no signal cleared the T-bill gate.
        </p>
      ) : (
        <>
          <table className="w-full text-sm mt-3">
            <thead className="text-left text-[10px] uppercase tracking-eyebrow text-muted border-b border-rule">
              <tr>
                <th className="px-3 py-2 font-medium">Symbol</th>
                <th className="px-3 py-2 font-medium text-right">Weight</th>
                <th className="px-3 py-2 font-medium text-right">Price</th>
                <th className="px-3 py-2 font-medium text-right">Shares</th>
                <th className="px-3 py-2 font-medium text-right">Notional</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(([sym, a]) => (
                <tr key={sym} className="border-b border-rule/40 last:border-0">
                  <td className="px-3 py-2 font-medium">{sym}</td>
                  <td className="px-3 py-2 text-right num">
                    {(a.weight * 100).toFixed(1)}%
                  </td>
                  <td className="px-3 py-2 text-right num">
                    {sym === "CASH" ? "—" : `$${a.price.toFixed(2)}`}
                  </td>
                  <td className="px-3 py-2 text-right num">
                    {sym === "CASH" ? "—" : a.shares}
                  </td>
                  <td className="px-3 py-2 text-right num">
                    {sym === "CASH"
                      ? formatMoney(principal * a.weight)
                      : formatMoney(a.shares * a.price)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {residual > 0.01 && (
            <p className="text-[11px] text-muted mt-2 font-sans">
              Cash residual after share rounding: {formatMoney(residual)}
            </p>
          )}
        </>
      )}
    </article>
  );
}

function Empty() {
  return (
    <div className="card px-8 py-16 text-center">
      <h1 className="font-serif text-2xl font-semibold">No cached recommendations</h1>
      <p className="text-muted mt-3 text-sm">Run from the terminal:</p>
      <pre className="font-mono text-xs bg-rule/40 inline-block mt-4 px-4 py-2 rounded">
        python3 -m fund.cache_for_ui
      </pre>
    </div>
  );
}
