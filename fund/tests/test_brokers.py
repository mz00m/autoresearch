"""Broker adapters — Alpaca REST mocking + IBKR import fallback."""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fund.brokers import BrokerOrderAck, load_broker
from fund.brokers.alpaca import AlpacaBroker


class _FakeResp:
    def __init__(self, body: bytes):
        self._body = body
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def read(self) -> bytes:
        return self._body


def _patch(payloads: dict[str, dict | list], captured: dict):
    """Patch urlopen to return JSON keyed by request method+path."""
    orig = urllib.request.urlopen
    def fake(req, timeout=15):
        key = f"{req.get_method()} {req.full_url.split('?')[0].split('alpaca.markets')[-1]}"
        captured.setdefault("calls", []).append({
            "method": req.get_method(),
            "url": req.full_url,
            "body": req.data.decode() if req.data else None,
            "headers": dict(req.headers),
        })
        payload = payloads.get(key, {})
        return _FakeResp(json.dumps(payload).encode())
    urllib.request.urlopen = fake
    return orig


def _restore(orig):
    urllib.request.urlopen = orig


def _ticket(side="BUY", sym="SPY", qty=10, ref=400.0):
    from fund.portfolio import Ticket
    return Ticket(ticket_id="abc12345", created="2024-01-01", symbol=sym,
                  side=side, qty=qty, ref_price=ref, rationale="test",
                  risk_max_loss=qty * ref)


# --- Alpaca tests -----------------------------------------------------------

def test_alpaca_missing_credentials_raises():
    # Clear env first
    for k in ("ALPACA_API_KEY", "ALPACA_API_SECRET"):
        os.environ.pop(k, None)
    try:
        AlpacaBroker()
    except RuntimeError as e:
        assert "ALPACA_API_KEY" in str(e)
        return
    raise AssertionError("expected RuntimeError for missing creds")


def test_alpaca_place_order_builds_market_day_payload():
    b = AlpacaBroker(api_key="k", api_secret="s")
    captured: dict = {}
    orig = _patch({"POST /v2/orders": {"id": "ord-1", "status": "new"}}, captured)
    try:
        ack = b.place_order(_ticket("BUY", "SPY", 10, 400.0))
    finally:
        _restore(orig)
    assert ack.status == "pending"
    assert ack.broker_order_id == "ord-1"
    body = json.loads(captured["calls"][0]["body"])
    assert body == {"symbol": "SPY", "qty": "10", "side": "buy",
                    "type": "market", "time_in_force": "day",
                    "client_order_id": "fund-abc12345"}


def test_alpaca_threads_ticket_id_through_client_order_id():
    b = AlpacaBroker(api_key="k", api_secret="s")
    captured: dict = {}
    orig = _patch({"POST /v2/orders": {"id": "x"}}, captured)
    try:
        b.place_order(_ticket("SELL", "AGG", 5, 88.0))
    finally:
        _restore(orig)
    body = json.loads(captured["calls"][0]["body"])
    assert body["client_order_id"] == "fund-abc12345"
    assert body["side"] == "sell"


def test_alpaca_fills_since_extracts_filled_orders():
    b = AlpacaBroker(api_key="k", api_secret="s")
    payload = [
        {"id": "o1", "symbol": "SPY", "side": "buy", "status": "filled",
         "filled_qty": "10", "filled_avg_price": "405.50",
         "client_order_id": "fund-t1",
         "filled_at": "2024-08-30T14:30:00Z"},
        {"id": "o2", "symbol": "AGG", "side": "buy", "status": "canceled",
         "client_order_id": "fund-t2"},
        {"id": "o3", "symbol": "QQQ", "side": "sell", "status": "filled",
         "filled_qty": "3", "filled_avg_price": "450.10",
         "client_order_id": "fund-t3",
         "filled_at": "2024-08-30T15:00:00Z"},
    ]
    captured: dict = {}
    orig = _patch({"GET /v2/orders": payload}, captured)
    try:
        fills = b.fills_since(date(2024, 8, 30))
    finally:
        _restore(orig)
    assert len(fills) == 2
    assert fills[0].ticket_id == "t1"
    assert fills[0].fill_price == 405.50
    assert fills[1].ticket_id == "t3"
    assert fills[1].side == "SELL"


def test_alpaca_account_snapshot_pulls_cash_and_positions():
    b = AlpacaBroker(api_key="k", api_secret="s")
    captured: dict = {}
    orig = _patch({
        "GET /v2/account": {"cash": "10000.5", "buying_power": "20001.0"},
        "GET /v2/positions": [
            {"symbol": "SPY", "qty": "36"},
            {"symbol": "AGG", "qty": "113"},
        ],
    }, captured)
    try:
        snap = b.account_snapshot()
    finally:
        _restore(orig)
    assert snap.cash == 10000.5
    assert snap.buying_power == 20001.0
    assert snap.positions == {"SPY": 36, "AGG": 113}


def test_alpaca_skips_partial_or_zero_fills():
    """Defensive: fills with 0 qty or 0 price are dropped (broker glitches)."""
    b = AlpacaBroker(api_key="k", api_secret="s")
    payload = [
        {"id": "o1", "symbol": "SPY", "side": "buy", "status": "filled",
         "filled_qty": "0", "filled_avg_price": "0",
         "client_order_id": "fund-t1"},
    ]
    captured: dict = {}
    orig = _patch({"GET /v2/orders": payload}, captured)
    try:
        fills = b.fills_since(date(2024, 8, 30))
    finally:
        _restore(orig)
    assert fills == []


# --- registry ---------------------------------------------------------------

def test_load_broker_unknown_raises():
    try:
        load_broker("nonexistent")
    except ValueError as e:
        assert "alpaca" in str(e) and "ibkr" in str(e)
        return
    raise AssertionError("expected ValueError for unknown broker")


def test_load_broker_alpaca_returns_alpaca():
    os.environ["ALPACA_API_KEY"] = "test-key"
    os.environ["ALPACA_API_SECRET"] = "test-secret"
    try:
        b = load_broker("alpaca")
        assert b.name == "alpaca"
    finally:
        os.environ.pop("ALPACA_API_KEY", None)
        os.environ.pop("ALPACA_API_SECRET", None)


def test_load_broker_ibkr_either_works_or_raises_clearly():
    """If ib_insync is installed, IbkrBroker constructs. If not, the import
    inside load_broker raises with a clear message."""
    try:
        b = load_broker("ibkr")
        assert b.name == "ibkr"
    except RuntimeError as e:
        assert "ib_insync" in str(e)


if __name__ == "__main__":
    tests = [(n, fn) for n, fn in globals().items()
             if n.startswith("test_") and callable(fn)]
    passed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS {name}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL {name}: {e}")
        except Exception as e:
            print(f"  FAIL {name}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
    sys.exit(0 if passed == len(tests) else 1)
