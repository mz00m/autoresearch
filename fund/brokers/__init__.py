"""Broker adapters — turn pending tickets into actual orders.

This module is *deliberately* minimal. The fund framework's risk engine has
already approved every ticket before it lands here; the broker's job is just
to route. Adapters do four things and four things only:

  1. ``place_order(ticket)``  — submit and return the broker's order id
  2. ``order_status(id)``     — pending / filled / rejected / canceled
  3. ``fills_since(date)``    — fills the broker has reported back
  4. ``account_snapshot()``   — cash + positions, for reconciliation

No adapter is allowed to *decide* anything. It can't resize, can't reject
on policy, can't add filters. Every policy decision happens upstream in the
risk engine and the morning guide. This module is a dumb wire.

Two adapters ship:

  * ``alpaca`` — pure-stdlib REST against paper-api.alpaca.markets. Five
    minutes to set up: sign up, paste two API keys in your shell env.
  * ``ibkr``   — ib_insync wrapper. Requires IB Gateway running and
    ``pip install ib_insync``. The right long-term home for live trading.

Pick one with ``--broker alpaca`` or ``--broker ibkr`` on send_orders.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class BrokerFill:
    """One execution as reported by the broker. ``ticket_id`` is *our* id,
    threaded through via the broker's client-order-id field at submission."""
    ticket_id: str
    broker_order_id: str
    symbol: str
    side: str          # BUY | SELL
    qty: int
    fill_price: float
    fill_time: datetime
    commission: float = 0.0


@dataclass(frozen=True)
class BrokerOrderAck:
    """Returned immediately after place_order. Does NOT mean filled — just
    accepted by the broker for routing."""
    ticket_id: str
    broker_order_id: str
    status: str        # pending | rejected
    reason: str = ""


@dataclass(frozen=True)
class AccountSnapshot:
    cash: float
    buying_power: float
    positions: dict[str, int]   # symbol -> shares


class Broker(Protocol):
    """The adapter contract. Stateless from the framework's point of view —
    each call is independent so we can swap adapters or reconnect freely."""

    name: str

    def place_order(self, ticket) -> BrokerOrderAck: ...
    def order_status(self, broker_order_id: str) -> str: ...
    def fills_since(self, since) -> list[BrokerFill]: ...
    def account_snapshot(self) -> AccountSnapshot: ...


def load_broker(name: str) -> Broker:
    """Resolve a broker by name. Imports are local so missing optional deps
    (ib_insync) only error when that broker is actually requested."""
    if name == "alpaca":
        from fund.brokers.alpaca import AlpacaBroker
        return AlpacaBroker()
    if name == "ibkr":
        from fund.brokers.ibkr import IbkrBroker
        return IbkrBroker()
    raise ValueError(f"unknown broker: {name!r}; try 'alpaca' or 'ibkr'")
