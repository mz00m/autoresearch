import {
  formatMoney,
  readUiCache,
  type ScorecardRow,
} from "@/lib/data";

export const dynamic = "force-dynamic";

export default async function ScorecardPage() {
  const cache = await readUiCache();
  const sc = cache?.scorecard;
  if (!cache || !sc || sc.error || !sc.rows?.length) {
    return (
      <div className="card px-8 py-12 text-center text-muted italic">
        No scorecard cached{sc?.error ? ` (${sc.error})` : ""} — run{" "}
        <code className="bg-rule/40 px-1 rounded">python3 -m fund.cache_for_ui</code>{" "}
        to generate it.
      </div>
    );
  }
  return (
    <div className="space-y-8">
      <header>
        <div className="eyebrow">Candidate selection</div>
        <h1 className="font-serif text-4xl font-semibold tracking-tight mt-2">
          Scorecard
        </h1>
        <p className="text-sm text-muted mt-2">
          Every candidate in the universe, ranked. As of{" "}
          <span className="num">{sc.as_of}</span> · regime{" "}
          <strong>{sc.regime ?? "—"}</strong>. Score = trend (≤55) + regime tilt
          (±10) + thesis (≤15) − fragility. It is a sort key for your attention,
          not an oracle — the columns are the point.
        </p>
      </header>

      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left border-b border-rule">
              <Th>#</Th>
              <Th>Symbol</Th>
              <Th>Class</Th>
              <Th right>Score</Th>
              <Th right>21d</Th>
              <Th right>63d</Th>
              <Th right>252d</Th>
              <Th right>&gt;200d</Th>
              <Th right>Vol</Th>
              <Th right>Worst 3d</Th>
              <Th right>Thesis</Th>
              <Th right>Held</Th>
              <Th>Why</Th>
            </tr>
          </thead>
          <tbody>
            {sc.rows.map((r, i) => (
              <Row key={r.symbol} r={r} rank={i + 1} />
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-[11px] text-muted font-sans">
        Trend = clipped multi-horizon momentum. Fragility = worst historical
        3-day drop (stops are triggers, not floors — see{" "}
        <code className="bg-rule/40 px-1 rounded">python3 -m fund.gap_stress</code>
        ). Thesis = your active conviction ×3. Selection still runs through the
        strategy bench, the risk engine, and your approval.
      </p>
    </div>
  );
}

function Th({
  children,
  right,
}: {
  children: React.ReactNode;
  right?: boolean;
}) {
  return (
    <th
      className={`kpi-label py-2 px-2 whitespace-nowrap ${right ? "text-right" : ""}`}
    >
      {children}
    </th>
  );
}

function pct(x: number | null, digits = 1) {
  if (x === null || x === undefined) return "—";
  return `${x > 0 ? "+" : ""}${(x * 100).toFixed(digits)}%`;
}

function tone(x: number | null) {
  if (x === null || x === undefined) return "text-muted";
  return x > 0 ? "text-ok" : x < 0 ? "text-alert" : "";
}

function Row({ r, rank }: { r: ScorecardRow; rank: number }) {
  const held = r.held_weight > 0;
  return (
    <tr
      className={`border-b border-rule/50 ${held ? "bg-paper" : ""}`}
    >
      <td className="py-2 px-2 num text-muted">{rank}</td>
      <td className="py-2 px-2 font-semibold whitespace-nowrap">
        {r.symbol}
        {held && (
          <span className="tag text-[9px] px-1.5 py-0.5 ml-2 rounded-sm">
            {(r.held_weight * 100).toFixed(0)}%
          </span>
        )}
      </td>
      <td className="py-2 px-2 text-muted whitespace-nowrap">
        {r.asset_class.replace("_", " ")}
      </td>
      <td className="py-2 px-2 num text-right font-semibold">
        {r.score.toFixed(1)}
      </td>
      <td className={`py-2 px-2 num text-right ${tone(r.r21)}`}>{pct(r.r21)}</td>
      <td className={`py-2 px-2 num text-right ${tone(r.r63)}`}>{pct(r.r63)}</td>
      <td className={`py-2 px-2 num text-right ${tone(r.r252)}`}>
        {pct(r.r252)}
      </td>
      <td className="py-2 px-2 text-right">
        {r.above_200d === null ? "—" : r.above_200d ? "✓" : "✗"}
      </td>
      <td className="py-2 px-2 num text-right">
        {r.vol_annualized === null ? "—" : `${(r.vol_annualized * 100).toFixed(0)}%`}
      </td>
      <td className={`py-2 px-2 num text-right ${tone(r.worst_3d)}`}>
        {pct(r.worst_3d)}
      </td>
      <td className="py-2 px-2 num text-right">
        {r.thesis_conviction ? `${r.thesis_conviction}/5` : "·"}
      </td>
      <td className={`py-2 px-2 num text-right ${tone(r.unrealized_pct)}`}>
        {held ? pct(r.unrealized_pct) : "·"}
      </td>
      <td className="py-2 px-2 text-[11px] text-muted whitespace-nowrap">
        {r.reason}
      </td>
    </tr>
  );
}
