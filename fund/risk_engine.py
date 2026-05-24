"""Deterministic risk engine — the sacred, un-modifiable safety core.

This is the investing analog of ``prepare.py`` in autoresearch: agents may
*read* it, but they must never modify it. It encodes the single hard rule of
this fund as deterministic Python rather than LLM judgment:

    You can lose up to 100% of the capital, but never more than 100%.
    No position may have a worst-case loss greater than the equity backing it,
    and the account can never go below zero.

The engine is *deny-by-default*: any instrument or order shape it does not
explicitly recognize as bounded-liability is rejected. No LLM, no strategy,
and no agent can route around it — every live order must clear ``check()``
before a human approves it.

Account modes:
  * CASH   — Phase 1. Bounded liability is structural (no borrowing possible).
             Orders are limited by *settled* cash.
  * MARGIN — Phase 2 (post-graduation). The same ``max_loss <= equity`` rule is
             now carried by *software* instead of the account type. Margin buys
             operational efficiency (capital recycling), never uncovered leverage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

OPTION_MULTIPLIER = 100  # shares per US equity-option contract


class AccountMode(str, Enum):
    CASH = "cash"
    MARGIN = "margin"


# --- Order kinds ------------------------------------------------------------
# Only kinds whose worst-case loss is provably <= the cash committed are
# whitelisted. Everything else (short stock, naked options, futures, any
# uncovered leverage) is absent on purpose and therefore denied by default.


class Kind(str, Enum):
    LONG_EQUITY = "long_equity"
    LONG_CALL = "long_call"
    LONG_PUT = "long_put"
    COVERED_CALL = "covered_call"
    CASH_SECURED_PUT = "cash_secured_put"
    DEBIT_SPREAD = "debit_spread"


@dataclass(frozen=True)
class Order:
    """A proposed position. Fields used depend on ``kind``.

    Conventions (all prices are per-share, in account currency):
      LONG_EQUITY      : qty (shares > 0), price
      LONG_CALL/PUT    : contracts (> 0), premium (per share paid)
      COVERED_CALL     : contracts (> 0), entry_price (underlying), premium (received)
      CASH_SECURED_PUT : contracts (> 0), strike, premium (received)
      DEBIT_SPREAD     : contracts (> 0), net_debit (per share, > 0)
    """

    kind: Kind
    symbol: str
    qty: float = 0.0          # shares (equity)
    contracts: float = 0.0    # option contracts
    price: float = 0.0
    entry_price: float = 0.0
    strike: float = 0.0
    premium: float = 0.0
    net_debit: float = 0.0
    note: str = ""


@dataclass(frozen=True)
class Verdict:
    approved: bool
    reasons: list[str]
    max_loss: float           # worst-case loss of THIS order
    cash_required: float      # cash/collateral this order ties up
    portfolio_max_loss_after: float  # total worst-case loss if this is added


# --- Worst-case loss handlers ----------------------------------------------
# Each returns (max_loss, cash_required). They must be conservative: assume the
# underlying goes to zero (or to the worst bounded outcome) for the holder.


def _long_equity(o: Order) -> tuple[float, float]:
    if o.qty <= 0 or o.price <= 0:
        raise ValueError("long_equity requires qty > 0 and price > 0")
    cost = o.qty * o.price
    return cost, cost  # stock -> 0


def _long_option(o: Order) -> tuple[float, float]:
    if o.contracts <= 0 or o.premium <= 0:
        raise ValueError("long option requires contracts > 0 and premium > 0")
    paid = o.contracts * OPTION_MULTIPLIER * o.premium
    return paid, paid  # option expires worthless


def _covered_call(o: Order) -> tuple[float, float]:
    if o.contracts <= 0 or o.entry_price <= 0 or o.premium < 0:
        raise ValueError("covered_call requires contracts>0, entry_price>0, premium>=0")
    shares = o.contracts * OPTION_MULTIPLIER
    received = shares * o.premium
    cost = shares * o.entry_price
    max_loss = cost - received          # underlying -> 0, keep premium
    cash_required = cost - received     # net outlay to establish
    return max_loss, cash_required


def _cash_secured_put(o: Order) -> tuple[float, float]:
    if o.contracts <= 0 or o.strike <= 0 or o.premium < 0:
        raise ValueError("cash_secured_put requires contracts>0, strike>0, premium>=0")
    shares = o.contracts * OPTION_MULTIPLIER
    received = shares * o.premium
    collateral = shares * o.strike      # fully cash-secured
    max_loss = collateral - received    # assigned, then underlying -> 0
    cash_required = collateral - received
    return max_loss, cash_required


def _debit_spread(o: Order) -> tuple[float, float]:
    if o.contracts <= 0 or o.net_debit <= 0:
        raise ValueError("debit_spread requires contracts > 0 and net_debit > 0")
    paid = o.contracts * OPTION_MULTIPLIER * o.net_debit
    return paid, paid  # max loss on a debit spread is the net debit


_HANDLERS: dict[Kind, Callable[[Order], tuple[float, float]]] = {
    Kind.LONG_EQUITY: _long_equity,
    Kind.LONG_CALL: _long_option,
    Kind.LONG_PUT: _long_option,
    Kind.COVERED_CALL: _covered_call,
    Kind.CASH_SECURED_PUT: _cash_secured_put,
    Kind.DEBIT_SPREAD: _debit_spread,
}


def worst_case_loss(order: Order) -> tuple[float, float]:
    """Return (max_loss, cash_required). Raises for unrecognized kinds."""
    handler = _HANDLERS.get(order.kind)
    if handler is None:
        raise ValueError(f"unsupported / forbidden order kind: {order.kind!r}")
    return handler(order)


# --- The engine -------------------------------------------------------------


@dataclass
class RiskEngine:
    """Holds account state and adjudicates orders. Deny-by-default."""

    principal: float
    equity: float
    mode: AccountMode = AccountMode.CASH
    settled_cash: float | None = None       # cash mode: usable now; defaults to equity
    open_positions_max_loss: float = 0.0    # sum of worst-case loss of open book
    drawdown_halt_frac: float | None = None  # e.g. 0.5 halts new risk if down 50%
    halted: bool = False
    _log: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.settled_cash is None:
            self.settled_cash = self.equity

    # -- core check ---------------------------------------------------------
    def check(self, order: Order) -> Verdict:
        reasons: list[str] = []

        if self.halted:
            reasons.append("ENGINE HALTED: kill-switch is active; no new risk allowed")

        # 1) instrument must be a recognized bounded-liability kind
        try:
            max_loss, cash_required = worst_case_loss(order)
        except ValueError as e:
            return Verdict(
                approved=False,
                reasons=[f"REJECT: {e}"],
                max_loss=float("inf"),
                cash_required=float("inf"),
                portfolio_max_loss_after=float("inf"),
            )

        # 2) THE rule: total worst-case loss must never exceed equity
        portfolio_after = self.open_positions_max_loss + max_loss
        if portfolio_after > self.equity + 1e-9:
            reasons.append(
                f"REJECT: portfolio worst-case loss {portfolio_after:,.2f} "
                f"would exceed equity {self.equity:,.2f} (the one rule)"
            )

        # 3) cash availability
        if self.mode is AccountMode.CASH:
            if cash_required > (self.settled_cash or 0.0) + 1e-9:
                reasons.append(
                    f"REJECT: needs {cash_required:,.2f} settled cash, "
                    f"only {self.settled_cash:,.2f} available (cash account)"
                )
        else:  # MARGIN: still bounded by equity, never uncovered leverage
            if cash_required > self.equity + 1e-9:
                reasons.append(
                    f"REJECT: cash/collateral {cash_required:,.2f} exceeds "
                    f"equity {self.equity:,.2f}"
                )

        # 4) optional drawdown circuit-breaker
        if self.drawdown_halt_frac is not None:
            floor = self.principal * (1.0 - self.drawdown_halt_frac)
            if self.equity < floor:
                reasons.append(
                    f"REJECT: equity {self.equity:,.2f} below drawdown-halt "
                    f"floor {floor:,.2f}; tripping kill-switch"
                )
                self.halted = True

        approved = len(reasons) == 0
        if approved:
            reasons.append("OK: bounded-liability, within equity and cash limits")
        return Verdict(
            approved=approved,
            reasons=reasons,
            max_loss=max_loss,
            cash_required=cash_required,
            portfolio_max_loss_after=portfolio_after,
        )

    # -- apply (only after human approval) ----------------------------------
    def apply(self, order: Order) -> Verdict:
        """Commit an order to the book. Re-checks first; never bypasses check()."""
        v = self.check(order)
        if not v.approved:
            raise PermissionError(f"cannot apply rejected order: {v.reasons}")
        self.open_positions_max_loss = v.portfolio_max_loss_after
        if self.mode is AccountMode.CASH:
            self.settled_cash = (self.settled_cash or 0.0) - v.cash_required
        self._log.append(f"APPLIED {order.kind.value} {order.symbol} "
                         f"max_loss={v.max_loss:,.2f}")
        return v
