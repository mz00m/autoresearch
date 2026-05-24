import type { Position } from "@/lib/data";
import { formatMoney } from "@/lib/data";

export function HoldingsTable({
  positions,
  cash,
  prices,
}: {
  positions: Record<string, Position>;
  cash: number;
  prices: Record<string, number>;
}) {
  const rows = Object.entries(positions).filter(([, p]) => p.qty > 0);
  if (rows.length === 0) {
    return (
      <div className="card px-6 py-8 text-muted italic">
        All cash · {formatMoney(cash)}
      </div>
    );
  }
  return (
    <div className="card overflow-hidden">
      <table className="w-full text-sm">
        <thead className="text-left text-[10px] uppercase tracking-eyebrow text-muted border-b border-rule">
          <tr>
            <th className="px-4 py-3 font-medium">Symbol</th>
            <th className="px-4 py-3 font-medium text-right">Qty</th>
            <th className="px-4 py-3 font-medium text-right">Avg cost</th>
            <th className="px-4 py-3 font-medium text-right">Last</th>
            <th className="px-4 py-3 font-medium text-right">Market value</th>
            <th className="px-4 py-3 font-medium text-right">Unrealized</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([sym, p]) => {
            const last = prices[sym] ?? p.avg_cost;
            const mv = p.qty * last;
            const unreal = (last - p.avg_cost) * p.qty;
            const unrealClass =
              unreal > 0 ? "text-ok" : unreal < 0 ? "text-alert" : "";
            return (
              <tr key={sym} className="border-b border-rule/60 last:border-0">
                <td className="px-4 py-3 font-medium">{sym}</td>
                <td className="px-4 py-3 text-right num">{p.qty}</td>
                <td className="px-4 py-3 text-right num">
                  {formatMoney(p.avg_cost)}
                </td>
                <td className="px-4 py-3 text-right num">
                  {formatMoney(last)}
                </td>
                <td className="px-4 py-3 text-right num">{formatMoney(mv)}</td>
                <td className={`px-4 py-3 text-right num ${unrealClass}`}>
                  {unreal >= 0 ? "+" : ""}
                  {formatMoney(unreal)}
                </td>
              </tr>
            );
          })}
          <tr className="bg-rule/20">
            <td className="px-4 py-3 font-medium text-muted">Cash</td>
            <td colSpan={3}></td>
            <td className="px-4 py-3 text-right num font-medium">
              {formatMoney(cash)}
            </td>
            <td></td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}
