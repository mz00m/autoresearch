"""Multi-strategy allocator — explicit weighted blend across the bench.

The single-strategy regime (set ``active_strategy`` to one name) is the right
default for clarity, but it's an unforced choice. A real fund typically runs
multiple strategies with a risk budget: e.g., 60% momentum + 30% defensive +
10% cash. This wrapper expresses that directly.

For each ``(strategy_name, params, weight)`` in the bench, it computes the
underlying's target weights and adds them in. CASH allocations bubble up to a
shared cash bucket. The result is a single dict of target weights that the
existing morning / closeout / risk_engine pipeline handles unchanged.

Constraints respected:
  * weights must sum to 1.0 (raises if not)
  * each underlying strategy still sees the full PIT-sliced panel
  * the risk engine + concentration caps still adjudicate every BUY

What this does NOT do:
  * solve a portfolio optimization (no covariance, no max-Sharpe);
    it's a literal weighted combination — the simplest thing that works
  * dynamically rebalance the inter-strategy weights (those are static;
    re-deploy with new weights to change them)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fund.data.pit import Panel, PriceSeries
from fund.strategy.dual_momentum import CASH


@dataclass(frozen=True)
class MultiStrategy:
    """A weighted blend of underlying strategies.

    ``allocations`` is a tuple of (strategy_name, params_dict, weight) triples.
    Weights must sum to 1.0 (cash slots are explicit: ('cash', {}, w)).
    """
    allocations: tuple[tuple[str, dict, float], ...]
    _validated: bool = field(default=False, init=False, repr=False)

    def __post_init__(self):
        total = sum(w for _, _, w in self.allocations)
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"MultiStrategy allocations must sum to 1.0, got {total:.6f}"
            )

    @property
    def n_params(self) -> int:
        # One implicit knob: the choice of weights. Each underlying's params
        # are architectural here, not tuned by this wrapper.
        return len(self.allocations)

    @property
    def name(self) -> str:
        parts = [f"{int(w * 100)}% {n}" for n, _, w in self.allocations]
        return "multi (" + " + ".join(parts) + ")"

    def target_weights(self, panel_asof: Panel,
                       tbill_asof: PriceSeries) -> dict[str, float]:
        from fund.strategy.registry import build as build_strategy

        blended: dict[str, float] = {}
        for name, params, w in self.allocations:
            if w <= 0:
                continue
            if name == "cash":
                blended[CASH] = blended.get(CASH, 0.0) + w
                continue
            try:
                strat = build_strategy(name, params)
                inner = strat.target_weights(panel_asof, tbill_asof)
            except Exception:
                # underlying broke — donate this slice to cash so we don't
                # silently overweight the rest
                blended[CASH] = blended.get(CASH, 0.0) + w
                continue
            for sym, sw in inner.items():
                blended[sym] = blended.get(sym, 0.0) + w * sw

        # Numerical hygiene
        total = sum(blended.values())
        if total <= 0:
            return {CASH: 1.0}
        if abs(total - 1.0) > 1e-3:
            # The underlying strategies should each sum to 1; if a sub-strategy
            # returned all-cash CASH:1, that already lands in the cash bucket.
            # A meaningful discrepancy means a strategy returned partial weights
            # (probably a bug in that strategy); fix here by normalizing.
            blended = {k: v / total for k, v in blended.items()}
        return blended
