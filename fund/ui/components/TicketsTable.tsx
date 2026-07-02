import type { Ticket } from "@/lib/data";
import { formatMoney } from "@/lib/data";

export function TicketsTable({
  tickets,
  emptyText = "No tickets — portfolio is already at target.",
}: {
  tickets: Ticket[];
  emptyText?: string;
}) {
  if (tickets.length === 0) {
    return (
      <div className="card px-6 py-8 text-muted italic">{emptyText}</div>
    );
  }
  return (
    <div className="card overflow-hidden">
      <table className="w-full text-sm">
        <thead className="text-left text-[10px] uppercase tracking-eyebrow text-muted border-b border-rule">
          <tr>
            <th className="px-4 py-3 font-medium"></th>
            <th className="px-4 py-3 font-medium">Symbol</th>
            <th className="px-4 py-3 font-medium text-right">Qty</th>
            <th className="px-4 py-3 font-medium text-right">Ref price</th>
            <th className="px-4 py-3 font-medium text-right">Notional</th>
            <th className="px-4 py-3 font-medium">Rationale</th>
          </tr>
        </thead>
        <tbody>
          {tickets.map((t) => {
            const tagClass =
              t.status === "rejected"
                ? "tag-rejected"
                : t.side === "BUY"
                ? "tag-buy"
                : "tag-sell";
            const label = t.status === "pending" ? t.side : t.status.toUpperCase();
            return (
              <tr key={t.ticket_id} className="border-b border-rule/60 last:border-0">
                <td className="px-4 py-3">
                  <span className={`tag ${tagClass}`}>{label}</span>
                </td>
                <td className="px-4 py-3 font-medium">{t.symbol}</td>
                <td className="px-4 py-3 text-right num">{t.qty}</td>
                <td className="px-4 py-3 text-right num">
                  {formatMoney(t.ref_price)}
                </td>
                <td className="px-4 py-3 text-right num">
                  {formatMoney(t.ref_price * t.qty)}
                </td>
                <td className="px-4 py-3 text-xs text-ink/70 max-w-md">
                  {t.rationale}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
