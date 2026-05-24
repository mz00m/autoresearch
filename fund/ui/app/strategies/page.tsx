import { readPortfolio } from "@/lib/data";

export const dynamic = "force-dynamic";

type StrategyDoc = {
  id: string;
  name: string;
  params: { name: string; default: string }[];
  blurb: string;
  pitch: string;
};

const STRATEGIES: StrategyDoc[] = [
  {
    id: "sixty_forty",
    name: "60 / 40",
    params: [],
    blurb: "Fixed 60% SPY / 40% AGG, rebalanced monthly.",
    pitch:
      "Zero tunable knobs. The baseline every other candidate has to beat. If a strategy can't outperform this on a risk-adjusted basis, it shouldn't run.",
  },
  {
    id: "dual_momentum",
    name: "Dual momentum",
    params: [{ name: "lookback_days", default: "252" }],
    blurb:
      "Antonacci-style GEM. Hold the asset with the best trailing return, but only if it beats T-bills.",
    pitch:
      "Concentrates 100% into the single best trend. Big rallies, big regret. Long-only and gated by the T-bill — falls all-cash in risk-off regimes.",
  },
  {
    id: "risk_parity",
    name: "Risk parity (lite)",
    params: [{ name: "vol_window", default: "63" }],
    blurb:
      "Inverse-volatility weights across the universe. Bond-heavy by construction.",
    pitch:
      "Approximates equal-risk contributions under approximately equal correlations. The smooth-equity choice — small max drawdowns, modest upside.",
  },
  {
    id: "top_n_momentum",
    name: "Top-N momentum",
    params: [
      { name: "n", default: "2" },
      { name: "lookback_days", default: "126" },
    ],
    blurb:
      "Equal-weight top-N trending assets above the T-bill gate. Variance-reduced cousin of dual_momentum.",
    pitch:
      "Trades some upside for variance reduction. Two assets at half-weight instead of one at full weight.",
  },
  {
    id: "ma_crossover",
    name: "MA crossover",
    params: [
      { name: "fast", default: "50" },
      { name: "slow", default: "200" },
    ],
    blurb:
      "Classic 50/200 SMA regime filter. Long the asset above the crossover, cash below.",
    pitch:
      "Slow on purpose. Misses tops and bottoms but rarely whipsawed. Two knobs = higher overfit surface, so it must clear a meaningfully higher bar to be worth running.",
  },
];

export default async function StrategiesPage() {
  const pf = await readPortfolio();
  const active = pf?.active_strategy;
  return (
    <div className="space-y-10">
      <header>
        <div className="eyebrow">Bench</div>
        <h1 className="font-serif text-4xl font-semibold tracking-tight mt-2">
          Strategy library
        </h1>
        <p className="text-sm text-muted mt-2 max-w-2xl">
          The active strategy lives as a string in{" "}
          <code className="font-mono bg-rule/40 px-1 rounded">
            portfolio_state.json
          </code>
          . Switching is a human commit (git-logged), not an LLM whim. Add a
          strategy by writing one file in <code className="font-mono">strategy/</code>{" "}
          and one entry in <code className="font-mono">strategy/registry.py</code>.
        </p>
      </header>

      <div className="grid gap-4">
        {STRATEGIES.map((s) => {
          const isActive = s.id === active;
          return (
            <article
              key={s.id}
              className={`card px-6 py-5 ${
                isActive ? "border-accent border-2" : ""
              }`}
            >
              <div className="flex items-baseline justify-between gap-4">
                <div className="flex items-baseline gap-3">
                  <h2 className="font-serif text-xl font-semibold">{s.name}</h2>
                  <code className="text-xs font-mono text-muted">{s.id}</code>
                  {isActive && (
                    <span className="tag tag-filled">Active</span>
                  )}
                </div>
                <span className="text-xs text-muted">
                  {s.params.length} {s.params.length === 1 ? "param" : "params"}
                </span>
              </div>
              <p className="text-sm text-ink/80 mt-2">{s.blurb}</p>
              <p className="text-xs text-muted mt-2 italic">{s.pitch}</p>
              {s.params.length > 0 && (
                <div className="mt-4 pt-4 border-t border-rule grid grid-cols-2 sm:grid-cols-4 gap-3">
                  {s.params.map((p) => (
                    <div key={p.name}>
                      <div className="kpi-label">{p.name}</div>
                      <div className="text-sm font-mono mt-0.5">{p.default}</div>
                    </div>
                  ))}
                </div>
              )}
            </article>
          );
        })}
      </div>

      <section className="card px-6 py-5 bg-rule/20 border-dashed">
        <h3 className="font-serif text-lg font-semibold">Switching the active strategy</h3>
        <p className="text-sm text-muted mt-2">
          Currently a manual edit; an explicit CLI is on the roadmap:
        </p>
        <pre className="font-mono text-xs bg-paper border border-rule rounded p-3 mt-3 overflow-x-auto">
{`# 1. Sell your current book to cash, then run:
python3 -m fund.portfolio init \\
  --principal $(jq .principal fund/portfolio_state.json) \\
  --strategy dual_momentum --force

# 2. Tomorrow morning, the guide will rebuild positions into the new strategy.`}
        </pre>
      </section>
    </div>
  );
}
