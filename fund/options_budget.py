"""Options premium budget — the deterministic rail around the asymmetric layer.

Long calls are the one whitelisted instrument that can quietly bleed the
account: each position is bounded (§2 holds), but *repeated* premium spend is
not — 5% of book per call across 3-4 conviction names, monthly, is a 100%+
annualized burn if the calls keep expiring worthless. Every other layer of this
fund has a hard deterministic rail; this module gives the options layer one:

    Rolling-12-month premium spend may not exceed ANNUAL_BUDGET_PCT of book.

The suggester reads the remaining budget and trims/refuses suggestions that
would exceed it. Actual fills are recorded here (``--record`` on the suggester
CLI) so the budget reflects reality, not intentions. Spend history is an
append-only JSON list — same auditability rules as the research ledger.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import date, timedelta

ANNUAL_BUDGET_PCT = 0.12   # max rolling-12mo premium spend as fraction of book


def _default_path() -> str:
    env = os.environ.get("FUND_OPTIONS_SPEND_PATH")
    if env:
        return env
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "options_spend.json")


@dataclass(frozen=True)
class PremiumSpend:
    on: str          # ISO date of the fill
    symbol: str
    cost: float      # total premium paid (always > 0)
    note: str = ""


def load_spends(path: str | None = None) -> list[PremiumSpend]:
    p = path or _default_path()
    if not os.path.exists(p):
        return []
    with open(p) as f:
        return [PremiumSpend(**row) for row in json.load(f)]


def record(symbol: str, cost: float, on: date, note: str = "",
           path: str | None = None) -> None:
    """Append one actual premium fill. Never edits or removes prior rows."""
    if cost <= 0:
        raise ValueError("premium cost must be > 0")
    p = path or _default_path()
    rows = [asdict(s) for s in load_spends(p)]
    rows.append(asdict(PremiumSpend(on=on.isoformat(), symbol=symbol.upper(),
                                    cost=cost, note=note)))
    with open(p, "w") as f:
        json.dump(rows, f, indent=2)


def spent_trailing(asof: date, days: int = 365,
                   path: str | None = None) -> float:
    """Total premium spent in the trailing window ending at ``asof``."""
    floor = asof - timedelta(days=days)
    return sum(s.cost for s in load_spends(path)
               if floor < date.fromisoformat(s.on) <= asof)


def remaining(book_value: float, asof: date, *,
              annual_pct: float = ANNUAL_BUDGET_PCT,
              path: str | None = None) -> float:
    """Premium dollars still spendable in the rolling year. Never negative."""
    budget = book_value * annual_pct
    return max(0.0, budget - spent_trailing(asof, path=path))
