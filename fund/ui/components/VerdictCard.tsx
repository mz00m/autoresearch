import type { Decision } from "@/lib/data";
import { formatPct, formatPp } from "@/lib/data";

const VARIANTS = {
  ok: {
    border: "border-l-ok",
    text: "text-ok",
    label: "On track",
  },
  watch: {
    border: "border-l-watch",
    text: "text-watch",
    label: "Watching",
  },
  iterate: {
    border: "border-l-alert",
    text: "text-alert",
    label: "Consider iterating",
  },
} as const;

export function VerdictCard({ decision }: { decision: Decision }) {
  const v = VARIANTS[decision.verdict];
  const showSuggestion = decision.verdict !== "ok" && decision.n_days > 0;
  return (
    <div className={`card border-l-4 ${v.border} px-6 py-5`}>
      <div className="flex items-baseline justify-between gap-4">
        <div>
          <div className="eyebrow">
            Decision &middot; {decision.n_days || "—"}-day trailing
          </div>
          <div className={`font-serif text-2xl font-semibold mt-1 ${v.text}`}>
            {v.label}
          </div>
        </div>
        {decision.n_days > 0 && (
          <div className="hidden sm:block text-right">
            <div className="kpi-label">Excess vs SPY</div>
            <div
              className={`text-xl num font-medium ${
                decision.trailing_excess >= 0 ? "text-ok" : "text-alert"
              }`}
            >
              {formatPp(decision.trailing_excess)}
            </div>
          </div>
        )}
      </div>
      <p className="text-sm text-ink/80 mt-3">{decision.reason}</p>
      {showSuggestion && (
        <p className="text-xs text-muted mt-3">
          Run{" "}
          <code className="font-mono bg-rule/60 px-1.5 py-0.5 rounded">
            python3 -m fund.compare --days 60
          </code>{" "}
          to see if any other bench strategy would have done better in this window.
        </p>
      )}
      {decision.n_days > 0 && (
        <div className="mt-4 pt-4 border-t border-rule grid grid-cols-2 sm:grid-cols-5 gap-4 text-xs">
          <Stat label="Portfolio" v={formatPct(decision.trailing_return)} />
          <Stat label="SPY" v={formatPct(decision.trailing_benchmark)} muted />
          <Stat
            label="Hit rate"
            v={`${(decision.hit_rate * 100).toFixed(0)}%`}
          />
          <Stat label="Worst day" v={formatPct(decision.worst_day)} />
          <Stat
            label="Drawdown"
            v={`-${(decision.current_drawdown * 100).toFixed(2)}%`}
          />
        </div>
      )}
    </div>
  );
}

function Stat({
  label,
  v,
  muted = false,
}: {
  label: string;
  v: string;
  muted?: boolean;
}) {
  return (
    <div>
      <div className="kpi-label">{label}</div>
      <div className={`num text-sm mt-0.5 ${muted ? "text-muted" : ""}`}>{v}</div>
    </div>
  );
}
