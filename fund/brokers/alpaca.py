"""Alpaca paper/live REST adapter — pure stdlib, no SDK needed.

The fastest broker to wire up: sign up at alpaca.markets, grab a paper-account
API key + secret, drop them in your shell env, you're done:

    export ALPACA_API_KEY="PK..."
    export ALPACA_API_SECRET="..."
    # optional, defaults to paper:
    export ALPACA_BASE_URL="https://paper-api.alpaca.markets"   # paper (default)
    # export ALPACA_BASE_URL="https://api.alpaca.markets"       # LIVE

Then:

    python3 -m fund.send_orders --broker alpaca

The adapter uses Alpaca's v2 REST surface — orders, fills, positions, account.
No websocket subscription needed: we just poll for fills during closeout.
Whole-share market orders only (matches our ticket shape).

Limits Alpaca itself enforces: US equities + ETFs only, regular trading hours,
no leveraged products on cash accounts, no options on paper accounts (so the
options strategies in the bench can't go live here — IBKR for those).
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone

from fund.brokers import AccountSnapshot, BrokerFill, BrokerOrderAck


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso_z(ts: str) -> datetime:
    """Alpaca returns '2024-08-30T14:30:01.234Z' — normalize."""
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


class AlpacaBroker:
    """Pure-stdlib Alpaca v2 client. Reads creds from env."""

    name = "alpaca"

    def __init__(self,
                 api_key: str | None = None,
                 api_secret: str | None = None,
                 base_url: str | None = None,
                 timeout: int = 15):
        self.api_key = api_key or os.environ.get("ALPACA_API_KEY")
        self.api_secret = api_secret or os.environ.get("ALPACA_API_SECRET")
        self.base_url = (base_url or os.environ.get("ALPACA_BASE_URL")
                         or "https://paper-api.alpaca.markets").rstrip("/")
        self.timeout = timeout
        if not (self.api_key and self.api_secret):
            raise RuntimeError(
                "Alpaca credentials missing — set ALPACA_API_KEY + "
                "ALPACA_API_SECRET in your shell env. Get them at "
                "https://app.alpaca.markets/ (paper accounts are free)."
            )

    # --- HTTP helpers ------------------------------------------------------

    def _req(self, method: str, path: str, *,
             body: dict | None = None,
             params: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={
                "APCA-API-KEY-ID": self.api_key or "",
                "APCA-API-SECRET-KEY": self.api_secret or "",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            raise RuntimeError(
                f"Alpaca {method} {path} -> HTTP {e.code}: {raw[:200]}"
            ) from e
        return json.loads(raw) if raw else {}

    # --- Broker interface --------------------------------------------------

    def place_order(self, ticket) -> BrokerOrderAck:
        body = {
            "symbol": ticket.symbol,
            "qty": str(int(ticket.qty)),
            "side": ticket.side.lower(),
            "type": "market",
            "time_in_force": "day",
            "client_order_id": f"fund-{ticket.ticket_id}",
        }
        try:
            resp = self._req("POST", "/v2/orders", body=body)
        except RuntimeError as e:
            return BrokerOrderAck(ticket_id=ticket.ticket_id,
                                  broker_order_id="", status="rejected",
                                  reason=str(e))
        return BrokerOrderAck(
            ticket_id=ticket.ticket_id,
            broker_order_id=resp.get("id", ""),
            status="pending",
        )

    def order_status(self, broker_order_id: str) -> str:
        try:
            o = self._req("GET", f"/v2/orders/{broker_order_id}")
        except RuntimeError:
            return "unknown"
        return (o.get("status") or "unknown").lower()

    def fills_since(self, since: date) -> list[BrokerFill]:
        params = {
            "status": "all",
            "after": f"{since.isoformat()}T00:00:00Z",
            "limit": "500",
            "direction": "asc",
        }
        rows = self._req("GET", "/v2/orders", params=params)
        if not isinstance(rows, list):
            return []
        out: list[BrokerFill] = []
        for o in rows:
            if (o.get("status") or "").lower() != "filled":
                continue
            client_id = o.get("client_order_id") or ""
            ticket_id = client_id[len("fund-"):] if client_id.startswith("fund-") else ""
            try:
                qty = int(float(o.get("filled_qty") or 0))
                price = float(o.get("filled_avg_price") or 0.0)
            except ValueError:
                continue
            if qty <= 0 or price <= 0:
                continue
            out.append(BrokerFill(
                ticket_id=ticket_id,
                broker_order_id=o.get("id") or "",
                symbol=(o.get("symbol") or "").upper(),
                side=(o.get("side") or "").upper(),
                qty=qty,
                fill_price=price,
                fill_time=_iso_z(o.get("filled_at")
                                 or o.get("submitted_at")
                                 or _now_utc().isoformat()),
                commission=0.0,   # Alpaca is commission-free
            ))
        return out

    def place_trailing_stop(self, symbol: str, qty: float,
                            trail_percent: float,
                            client_id: str | None = None) -> dict:
        """POST a trailing-stop SELL. Triggers a market sell if price drops
        `trail_percent` from its rolling peak. GTC. Broker re-anchors the
        trigger up as the price climbs — locks in gains automatically."""
        body = {
            "symbol": symbol.upper(),
            "qty": str(qty),
            "side": "sell",
            "type": "trailing_stop",
            "time_in_force": "gtc",
            "trail_percent": str(trail_percent),
        }
        if client_id:
            body["client_order_id"] = client_id
        try:
            return self._req("POST", "/v2/orders", body=body)
        except RuntimeError as e:
            return {"error": str(e)}

    def open_stops_for(self, symbol: str) -> list[dict]:
        """Existing open stop / trailing_stop SELL orders for `symbol`.
        Used to avoid double-stopping a position."""
        try:
            rows = self._req("GET", "/v2/orders",
                              params={"status": "open",
                                      "symbols": symbol.upper(),
                                      "limit": "50"})
        except RuntimeError:
            return []
        if not isinstance(rows, list):
            return []
        return [r for r in rows
                if (r.get("side") or "").lower() == "sell"
                and (r.get("type") or "") in ("stop", "trailing_stop")]

    def cancel_open_orders(self) -> dict:
        """DELETE /v2/orders — cancels every open order at the broker.
        Returns {"canceled": N, "errors": [...]}."""
        # Get the list first so we can report what was canceled
        opens = self._req("GET", "/v2/orders",
                          params={"status": "open", "limit": "500"})
        if not isinstance(opens, list):
            opens = []
        canceled = 0
        errors: list[str] = []
        for o in opens:
            oid = o.get("id")
            if not oid:
                continue
            try:
                self._req("DELETE", f"/v2/orders/{oid}")
                canceled += 1
            except RuntimeError as e:
                errors.append(f"{o.get('symbol','?')} {oid}: {e}")
        return {"canceled": canceled, "errors": errors,
                "would_have_canceled": [
                    {"symbol": o.get("symbol"), "side": o.get("side"),
                     "qty": o.get("qty"), "client_order_id": o.get("client_order_id")}
                    for o in opens
                ]}

    def account_snapshot(self) -> AccountSnapshot:
        acct = self._req("GET", "/v2/account")
        positions_raw = self._req("GET", "/v2/positions")
        positions: dict[str, int] = {}
        if isinstance(positions_raw, list):
            for p in positions_raw:
                try:
                    positions[(p.get("symbol") or "").upper()] = int(
                        float(p.get("qty") or 0))
                except ValueError:
                    continue
        return AccountSnapshot(
            cash=float(acct.get("cash") or 0.0),
            buying_power=float(acct.get("buying_power") or 0.0),
            positions=positions,
        )
