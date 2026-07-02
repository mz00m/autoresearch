"""Tax-lot accounting and wash-sale logic.

Active strategies that rotate monthly produce a lot of taxable events. At a
$25k taxable account this is non-trivial — short-term capital gains tax can
eat 100-200 bps/year if you let the system harvest gains without thought.

Three things this module gives you:

  1. **TaxLot** — date_acquired + qty + cost_per_share. A position is a list
     of lots, not a single (qty, avg_cost) pair. Required to compute holding
     period and realized PnL per sale.

  2. **Lot-selection policies** for SELL orders:
       FIFO          — oldest first (most brokers' default, simple)
       LIFO          — newest first
       HIFO          — highest cost first (best for harvesting losses)
       LT_FIRST      — long-term (>1 year) lots first (lowest tax rate)
       TAX_OPTIMAL   — long-term losses → ST losses → LT gains → ST gains
                       (industry-standard tax-aware ordering)

  3. **Wash-sale window** — if a symbol was sold at a loss within the last
     30 days, buying it back voids the loss deduction (IRC §1091). The check
     surfaces would-be wash-sale BUYs so the morning guide can defer them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum

LONG_TERM_DAYS = 365  # IRS rule: >1 year for long-term treatment
WASH_SALE_WINDOW_DAYS = 30


class LotPolicy(str, Enum):
    FIFO = "fifo"
    LIFO = "lifo"
    HIFO = "hifo"
    LT_FIRST = "lt_first"
    TAX_OPTIMAL = "tax_optimal"


@dataclass
class TaxLot:
    """One acquisition lot of a symbol."""
    date_acquired: str    # ISO date
    qty: float
    cost_per_share: float

    def holding_period_days(self, on: date) -> int:
        return (on - date.fromisoformat(self.date_acquired)).days

    def is_long_term(self, on: date) -> bool:
        return self.holding_period_days(on) > LONG_TERM_DAYS


@dataclass
class RealizedLot:
    """A lot sold against; the consumed portion and what it earned."""
    date_acquired: str
    date_sold: str
    qty: float
    cost_per_share: float
    sale_price: float
    long_term: bool

    @property
    def proceeds(self) -> float:
        return self.qty * self.sale_price

    @property
    def basis(self) -> float:
        return self.qty * self.cost_per_share

    @property
    def realized_pnl(self) -> float:
        return self.proceeds - self.basis


def _classify_lot_score(lot: TaxLot, on: date, current_price: float) -> tuple:
    """Sort key for TAX_OPTIMAL ordering: LT-loss → ST-loss → LT-gain → ST-gain.
    Within each bucket, prefer larger unrealized loss / smaller unrealized gain."""
    is_lt = lot.is_long_term(on)
    unrealized = (current_price - lot.cost_per_share) * lot.qty
    is_loss = unrealized < 0
    # Bucket: 0 = LT loss, 1 = ST loss, 2 = LT gain, 3 = ST gain
    if is_loss and is_lt:
        bucket = 0
    elif is_loss and not is_lt:
        bucket = 1
    elif not is_loss and is_lt:
        bucket = 2
    else:
        bucket = 3
    # Within bucket, prefer the most-negative pnl_per_share first (biggest loss harvest)
    return (bucket, unrealized / lot.qty if lot.qty else 0.0)


def select_lots_for_sale(
    lots: list[TaxLot], sale_qty: float, on: date,
    current_price: float, policy: LotPolicy = LotPolicy.TAX_OPTIMAL,
) -> list[tuple[TaxLot, float]]:
    """Pick (lot, qty_to_consume) pairs to satisfy `sale_qty`. Returns the
    list of partial-or-whole lots to sell, in order. Does not mutate input."""
    if sale_qty <= 0 or not lots:
        return []
    ordered = list(lots)
    if policy == LotPolicy.FIFO:
        ordered.sort(key=lambda l: l.date_acquired)
    elif policy == LotPolicy.LIFO:
        ordered.sort(key=lambda l: l.date_acquired, reverse=True)
    elif policy == LotPolicy.HIFO:
        ordered.sort(key=lambda l: -l.cost_per_share)
    elif policy == LotPolicy.LT_FIRST:
        ordered.sort(key=lambda l: (not l.is_long_term(on), l.date_acquired))
    elif policy == LotPolicy.TAX_OPTIMAL:
        ordered.sort(key=lambda l: _classify_lot_score(l, on, current_price))
    else:
        raise ValueError(f"unknown lot policy: {policy!r}")

    out: list[tuple[TaxLot, float]] = []
    remaining = sale_qty
    for lot in ordered:
        if remaining <= 1e-9:
            break
        take = min(lot.qty, remaining)
        if take > 1e-9:
            out.append((lot, take))
            remaining -= take
    return out


def realize_sale(
    lots: list[TaxLot], sale_qty: float, sale_price: float, on: date,
    policy: LotPolicy = LotPolicy.TAX_OPTIMAL,
) -> tuple[list[TaxLot], list[RealizedLot]]:
    """Apply a sale to a lots list. Returns (new_lots, realized_lots).
    The new_lots list has consumed lots removed (or trimmed); realized_lots
    is the per-lot PnL breakdown for tax reporting + wash-sale tracking."""
    plan = select_lots_for_sale(lots, sale_qty, on, sale_price, policy)
    remaining: dict[id, float] = {id(lot): lot.qty for lot in lots}
    realized: list[RealizedLot] = []
    for lot, take in plan:
        remaining[id(lot)] -= take
        realized.append(RealizedLot(
            date_acquired=lot.date_acquired, date_sold=on.isoformat(),
            qty=take, cost_per_share=lot.cost_per_share,
            sale_price=sale_price, long_term=lot.is_long_term(on),
        ))
    new_lots = [TaxLot(date_acquired=lot.date_acquired,
                       qty=remaining[id(lot)],
                       cost_per_share=lot.cost_per_share)
                for lot in lots if remaining[id(lot)] > 1e-9]
    return new_lots, realized


@dataclass(frozen=True)
class TaxSummary:
    st_gains: float = 0.0
    st_losses: float = 0.0
    lt_gains: float = 0.0
    lt_losses: float = 0.0

    @property
    def net_short_term(self) -> float:
        return self.st_gains + self.st_losses   # losses are negative

    @property
    def net_long_term(self) -> float:
        return self.lt_gains + self.lt_losses

    @property
    def net_total(self) -> float:
        return self.net_short_term + self.net_long_term


def summarize_realized(realized: list[RealizedLot]) -> TaxSummary:
    st_g = st_l = lt_g = lt_l = 0.0
    for r in realized:
        pnl = r.realized_pnl
        if r.long_term:
            if pnl >= 0:
                lt_g += pnl
            else:
                lt_l += pnl
        else:
            if pnl >= 0:
                st_g += pnl
            else:
                st_l += pnl
    return TaxSummary(st_gains=st_g, st_losses=st_l,
                      lt_gains=lt_g, lt_losses=lt_l)


# --- wash sale tracking ----------------------------------------------------

@dataclass(frozen=True)
class WashCheck:
    blocked: bool
    reason: str = ""
    days_until_clear: int = 0


def wash_sale_check(symbol: str, on: date,
                    last_loss_sales: dict[str, str],
                    window_days: int = WASH_SALE_WINDOW_DAYS) -> WashCheck:
    """If `symbol` was sold at a loss within `window_days` of `on`, flag the
    BUY as a wash sale (IRC §1091). The loss deduction would be voided."""
    sold_iso = last_loss_sales.get(symbol)
    if not sold_iso:
        return WashCheck(blocked=False)
    sold = date.fromisoformat(sold_iso)
    elapsed = (on - sold).days
    if 0 <= elapsed <= window_days:
        return WashCheck(
            blocked=True,
            reason=(f"wash-sale risk: {symbol} sold at a loss on {sold_iso} "
                    f"({elapsed}d ago); buying within {window_days}d voids the "
                    f"loss deduction"),
            days_until_clear=window_days - elapsed + 1,
        )
    return WashCheck(blocked=False)
