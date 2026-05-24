"""keep_awake.py — wrap `caffeinate` so the scheduler daemon actually runs.

launchd only fires jobs while macOS is awake. Plugging the laptop in usually
isn't enough — the system can still sleep after 30+ minutes of idle. This
spawns a detached `caffeinate -i` for a configurable window (default 24h)
so the scheduler is guaranteed to fire the overnight + morning jobs.

  python3 -m fund.keep_awake --start          # 24h block
  python3 -m fund.keep_awake --start --hours 48
  python3 -m fund.keep_awake --status
  python3 -m fund.keep_awake --stop

Idempotent — --start while one's already running just reports the existing
PID + remaining time. PID lives in ~/.fund/caffeinate.pid.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta

_STATE_DIR = os.path.expanduser("~/.fund")
_PID_PATH = os.path.join(_STATE_DIR, "caffeinate.pid")


def _read_state() -> dict | None:
    if not os.path.exists(_PID_PATH):
        return None
    try:
        with open(_PID_PATH) as f:
            return json.load(f)
    except Exception:
        return None


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def status() -> dict:
    st = _read_state()
    if not st:
        return {"running": False}
    pid = int(st.get("pid", 0))
    if not _alive(pid):
        # stale pidfile
        try:
            os.unlink(_PID_PATH)
        except Exception:
            pass
        return {"running": False, "stale_cleaned": True}
    expires_at = st.get("expires_at", "")
    remaining_seconds = 0
    if expires_at:
        try:
            remaining_seconds = int(
                (datetime.fromisoformat(expires_at) - datetime.now()).total_seconds())
        except Exception:
            pass
    return {
        "running": True,
        "pid": pid,
        "started_at": st.get("started_at"),
        "expires_at": expires_at,
        "remaining_seconds": max(0, remaining_seconds),
    }


def start(hours: float = 24.0) -> dict:
    existing = status()
    if existing.get("running"):
        return {"action": "already_running", **existing}
    os.makedirs(_STATE_DIR, exist_ok=True)
    seconds = int(hours * 3600)
    # -i = prevent idle sleep; -t = timeout in seconds (auto-cleanup)
    proc = subprocess.Popen(
        ["caffeinate", "-i", "-t", str(seconds)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,   # detach from parent
    )
    expires_at = (datetime.now() + timedelta(seconds=seconds)).isoformat(timespec="seconds")
    state = {"pid": proc.pid, "started_at": datetime.now().isoformat(timespec="seconds"),
             "expires_at": expires_at, "hours": hours}
    with open(_PID_PATH, "w") as f:
        json.dump(state, f, indent=2)
    return {"action": "started", **state}


def stop() -> dict:
    st = _read_state()
    if not st:
        return {"action": "not_running"}
    pid = int(st.get("pid", 0))
    killed = False
    if _alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
            time.sleep(0.3)
            killed = True
        except Exception:
            pass
    try:
        os.unlink(_PID_PATH)
    except Exception:
        pass
    return {"action": "stopped", "pid": pid, "killed": killed}


def main() -> int:
    ap = argparse.ArgumentParser(description="Wrap caffeinate so the scheduler runs.")
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--start", action="store_true")
    grp.add_argument("--stop", action="store_true")
    grp.add_argument("--status", action="store_true")
    ap.add_argument("--hours", type=float, default=24.0,
                    help="hours to stay awake (default 24)")
    args = ap.parse_args()
    if args.start:
        out = start(hours=args.hours)
    elif args.stop:
        out = stop()
    else:
        out = status()
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
