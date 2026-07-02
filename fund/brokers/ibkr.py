"""IBKR adapter via ib_insync — the long-term home for live trading.

Setup is heavier than Alpaca but the destination is the right one:

  1. Sign up at ibkr.com — paper accounts are free, same APIs as live.
  2. Install IB Gateway (or TWS) and enable API in settings:
       - Configure -> API -> Settings
       - Enable ActiveX and Socket Clients
       - Socket port: 7497 for paper, 7496 for live
       - Trusted IPs: 127.0.0.1
       - Uncheck "Read-Only API"
  3. ``pip install ib_insync`` (optional dep — only needed if you use IBKR)
  4. Launch IB Gateway, log in to your paper account, leave it running.
  5. ``export FUND_IBKR_PORT=7497`` (or set in your shell)
  6. ``python3 -m fund.send_orders --broker ibkr``

If ib_insync is not installed, importing this module raises a clear error.

Lifetime: connect → submit → poll → disconnect. We don't hold a persistent
session because the closeout call comes seconds later and reconnecting is
~1ms cheap. This keeps the adapter stateless from the framework's view.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone

from fund.brokers import AccountSnapshot, BrokerFill, BrokerOrderAck

try:
    from ib_insync import IB, MarketOrder, Stock, util  # type: ignore
    _IB_INSYNC_OK = True
    _IB_INSYNC_ERR = ""
except Exception as e:   # ImportError or version skew
    _IB_INSYNC_OK = False
    _IB_INSYNC_ERR = str(e)


def _require_ib_insync() -> None:
    if _IB_INSYNC_OK:
        return
    raise RuntimeError(
        "ib_insync not available — install with `pip install ib_insync`. "
        f"Underlying import error: {_IB_INSYNC_ERR}"
    )


class IbkrBroker:
    """Connect-per-call IB Gateway client. Stateless to the framework."""

    name = "ibkr"

    def __init__(self,
                 host: str | None = None,
                 port: int | None = None,
                 client_id: int | None = None,
                 timeout: int = 20):
        self.host = host or os.environ.get("FUND_IBKR_HOST", "127.0.0.1")
        self.port = int(port or os.environ.get("FUND_IBKR_PORT", "7497"))
        self.client_id = int(client_id or os.environ.get("FUND_IBKR_CLIENT_ID", "17"))
        self.timeout = timeout

    # --- session ----------------------------------------------------------

    def _connect(self) -> "IB":
        _require_ib_insync()
        ib = IB()
        ib.connect(self.host, self.port, clientId=self.client_id,
                   timeout=self.timeout, readonly=False)
        return ib

    # --- Broker interface -------------------------------------------------

    def place_order(self, ticket) -> BrokerOrderAck:
        try:
            ib = self._connect()
        except Exception as e:
            return BrokerOrderAck(ticket_id=ticket.ticket_id, broker_order_id="",
                                  status="rejected",
                                  reason=f"IB connect failed: {e}")
        try:
            contract = Stock(ticket.symbol, "SMART", "USD")
            ib.qualifyContracts(contract)
            order = MarketOrder(ticket.side, int(ticket.qty))
            # Thread our ticket id through the order ref so we can reconcile.
            order.orderRef = f"fund-{ticket.ticket_id}"
            trade = ib.placeOrder(contract, order)
            # Give IB a moment to acknowledge.
            ib.sleep(0.5)
            broker_order_id = str(trade.order.permId or trade.order.orderId or "")
            return BrokerOrderAck(
                ticket_id=ticket.ticket_id,
                broker_order_id=broker_order_id,
                status="pending",
            )
        except Exception as e:
            return BrokerOrderAck(ticket_id=ticket.ticket_id, broker_order_id="",
                                  status="rejected", reason=str(e))
        finally:
            try:
                ib.disconnect()
            except Exception:
                pass

    def order_status(self, broker_order_id: str) -> str:
        try:
            ib = self._connect()
        except Exception:
            return "unknown"
        try:
            for trade in ib.trades():
                if str(trade.order.permId or trade.order.orderId) == broker_order_id:
                    return (trade.orderStatus.status or "unknown").lower()
            return "unknown"
        finally:
            try:
                ib.disconnect()
            except Exception:
                pass

    def fills_since(self, since: date) -> list[BrokerFill]:
        try:
            ib = self._connect()
        except Exception:
            return []
        try:
            ib.reqExecutions()
            ib.sleep(0.5)
            out: list[BrokerFill] = []
            for fill in ib.fills():
                ts = fill.execution.time
                if hasattr(ts, "date") and ts.date() < since:
                    continue
                ref = (fill.execution.orderRef or "")
                ticket_id = ref[len("fund-"):] if ref.startswith("fund-") else ""
                qty = int(fill.execution.shares)
                if qty <= 0:
                    continue
                out.append(BrokerFill(
                    ticket_id=ticket_id,
                    broker_order_id=str(fill.execution.permId or fill.execution.orderId),
                    symbol=fill.contract.symbol.upper(),
                    side=fill.execution.side.upper(),
                    qty=qty,
                    fill_price=float(fill.execution.price),
                    fill_time=ts if isinstance(ts, datetime)
                              else datetime.now(timezone.utc),
                    commission=float(getattr(fill.commissionReport, "commission", 0.0) or 0.0),
                ))
            return out
        finally:
            try:
                ib.disconnect()
            except Exception:
                pass

    def account_snapshot(self) -> AccountSnapshot:
        try:
            ib = self._connect()
        except Exception:
            return AccountSnapshot(cash=0.0, buying_power=0.0, positions={})
        try:
            ib.sleep(0.5)
            account = ib.managedAccounts()[0] if ib.managedAccounts() else ""
            values = {v.tag: v.value for v in ib.accountValues(account)
                      if v.currency in ("USD", "BASE", "")}
            cash = float(values.get("TotalCashValue") or 0.0)
            bp = float(values.get("BuyingPower") or cash)
            positions: dict[str, int] = {}
            for p in ib.positions(account):
                try:
                    positions[p.contract.symbol.upper()] = int(float(p.position))
                except Exception:
                    continue
            return AccountSnapshot(cash=cash, buying_power=bp, positions=positions)
        finally:
            try:
                ib.disconnect()
            except Exception:
                pass
