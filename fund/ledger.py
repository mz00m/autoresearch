"""Append-only research ledger — the ``results.tsv`` analog.

Every strategy hypothesis the overnight factory evaluates lands here exactly
once, with its LOCKED out-of-sample numbers and a keep/discard/crash verdict.
Like autoresearch: advance (keep) on a real improvement, discard otherwise,
and never rewrite history. Git is the state machine; this file is the audit log.

TSV (tab-separated; commas break free-text descriptions). One header + N rows.
"""

from __future__ import annotations

import csv
import datetime as _dt
import os
from dataclasses import asdict, dataclass

LEDGER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "research_ledger.tsv")

FIELDS = [
    "timestamp", "strategy_id", "commit", "status",
    "oos_deflated_sharpe", "oos_sortino", "oos_max_dd",
    "n_trials", "n_params", "objective", "description",
]

VALID_STATUS = {"keep", "discard", "crash"}


@dataclass
class Entry:
    strategy_id: str
    commit: str
    status: str                 # keep | discard | crash
    oos_deflated_sharpe: float
    oos_sortino: float
    oos_max_dd: float
    n_trials: int
    n_params: int
    objective: float
    description: str
    timestamp: str = ""

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUS:
            raise ValueError(f"status must be one of {VALID_STATUS}, got {self.status!r}")
        if not self.timestamp:
            self.timestamp = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
        if "\t" in self.description or "\n" in self.description:
            raise ValueError("description must not contain tabs or newlines")


def _ensure_header(path: str) -> None:
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        with open(path, "w", newline="") as f:
            csv.writer(f, delimiter="\t").writerow(FIELDS)


def append(entry: Entry, path: str = LEDGER_PATH) -> None:
    """Append one immutable row. Never edits or removes existing rows."""
    _ensure_header(path)
    row = asdict(entry)
    with open(path, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=FIELDS, delimiter="\t").writerow(row)


def load(path: str = LEDGER_PATH) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def kept(path: str = LEDGER_PATH) -> list[dict]:
    """Return kept strategies, best objective first."""
    rows = [r for r in load(path) if r.get("status") == "keep"]
    return sorted(rows, key=lambda r: float(r.get("objective", 0.0)), reverse=True)


if __name__ == "__main__":
    # initialize an empty ledger with just the header
    _ensure_header(LEDGER_PATH)
    print(f"ledger ready at {LEDGER_PATH}")
