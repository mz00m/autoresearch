"""thesis.py — qualitative rationale for every held position.

Matt's observation: "math can only go so far with investing. You need an
industry or world informed thesis." Right. The deflated Sharpe machinery
tells us which signals would have survived noise in past data — silent
on whether the WORLD will keep behaving like the past.

A thesis is the human-written WHY behind a position:
  - Why this asset will outperform (the catalyst)
  - When that catalyst would invalidate (the kill switch)
  - How long the thesis is expected to remain valid (the horizon)

When the thesis breaks, EXIT regardless of what the momentum signal says.
When the signal says exit but the thesis still holds, the human can override.

This module is append-only — never edits a thesis, only adds new versions.
The full chain is auditable so we can review later "what did we believe at
the time we put this on?"

Storage: fund/theses.json — list of entries keyed by (symbol, version).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Optional

_THESES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "theses.json")


@dataclass
class Thesis:
    symbol: str
    catalyst: str       # WHY this asset will outperform — 1-2 sentences
    kill_switch: str    # what would have to happen for the thesis to BREAK
    horizon: str        # rough time window (e.g., "3-6 months", "until Q3 25 OPEC meeting")
    confidence: int     # 1-5 self-rated confidence
    created_at: str = ""  # ISO datetime — set automatically
    author: str = "matt"
    status: str = "active"   # active | invalidated | expired
    invalidated_at: str = ""  # ISO date when human marked invalidated
    invalidated_reason: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now().isoformat(timespec="seconds")
        if self.confidence < 1 or self.confidence > 5:
            raise ValueError("confidence must be 1-5")
        if self.status not in {"active", "invalidated", "expired"}:
            raise ValueError(f"invalid status {self.status!r}")


def _load() -> list[dict]:
    if not os.path.exists(_THESES_PATH):
        return []
    with open(_THESES_PATH) as f:
        return json.load(f)


def _save(rows: list[dict]) -> None:
    with open(_THESES_PATH, "w") as f:
        json.dump(rows, f, indent=2, default=str)


def add(thesis: Thesis) -> None:
    rows = _load()
    rows.append(asdict(thesis))
    _save(rows)


def invalidate(symbol: str, reason: str, on: date | None = None) -> bool:
    on = on or date.today()
    rows = _load()
    found = False
    for r in rows:
        if r["symbol"].upper() == symbol.upper() and r["status"] == "active":
            r["status"] = "invalidated"
            r["invalidated_at"] = on.isoformat()
            r["invalidated_reason"] = reason
            found = True
    if found:
        _save(rows)
    return found


def active_for(symbol: str) -> Optional[dict]:
    """Most recent active thesis for `symbol`, or None."""
    rows = _load()
    actives = [r for r in rows
               if r["symbol"].upper() == symbol.upper()
               and r["status"] == "active"]
    if not actives:
        return None
    return max(actives, key=lambda r: r["created_at"])


def all_for(symbol: str) -> list[dict]:
    rows = _load()
    return [r for r in rows if r["symbol"].upper() == symbol.upper()]


def all_active() -> list[dict]:
    return [r for r in _load() if r["status"] == "active"]


def all_records() -> list[dict]:
    return _load()


def missing_for_positions(symbols: list[str]) -> list[str]:
    """Held symbols that don't have an active thesis."""
    return [s for s in symbols if active_for(s) is None]


# --- CLI ------------------------------------------------------------------

def _cli_add() -> int:
    ap = argparse.ArgumentParser(description="Add a new thesis for a symbol.")
    ap.add_argument("add")   # positional consumed
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--catalyst", required=True)
    ap.add_argument("--kill-switch", required=True,
                    help="what would invalidate the thesis")
    ap.add_argument("--horizon", required=True)
    ap.add_argument("--confidence", type=int, required=True,
                    choices=[1, 2, 3, 4, 5])
    ap.add_argument("--author", default="matt")
    args = ap.parse_args()
    t = Thesis(symbol=args.symbol.upper(), catalyst=args.catalyst,
               kill_switch=args.kill_switch, horizon=args.horizon,
               confidence=args.confidence, author=args.author)
    add(t)
    print(f"added thesis for {t.symbol}  confidence={t.confidence}/5")
    return 0


def _cli_invalidate() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("invalidate")
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--reason", required=True)
    args = ap.parse_args()
    if invalidate(args.symbol, args.reason):
        print(f"invalidated thesis for {args.symbol.upper()}")
    else:
        print(f"no active thesis for {args.symbol.upper()}")
    return 0


def _cli_list() -> int:
    rows = all_records()
    if not rows:
        print("no theses recorded yet.")
        return 0
    for r in rows:
        marker = {"active": "●", "invalidated": "✗", "expired": "—"}[r["status"]]
        print(f"  {marker} {r['symbol']:<5}  confidence {r['confidence']}/5"
              f"  ({r['created_at']})")
        print(f"      catalyst: {r['catalyst']}")
        print(f"      kill:     {r['kill_switch']}")
        print(f"      horizon:  {r['horizon']}")
        if r["status"] == "invalidated":
            print(f"      ✗ INVALIDATED {r['invalidated_at']}: {r['invalidated_reason']}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "add":
            sys.exit(_cli_add())
        if sys.argv[1] == "invalidate":
            sys.exit(_cli_invalidate())
        if sys.argv[1] == "list":
            sys.exit(_cli_list())
    print("usage: python3 -m fund.thesis {add | invalidate | list} ...")
    sys.exit(2)
