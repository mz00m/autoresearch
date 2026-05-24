"""scheduler.py — the autonomous routine, ET-clock-aware.

What it does *without* a human:
  * 05:30 ET (well before open)  — refresh cards (fresh prices/regime)
  * 08:00 ET (before open)       — run morning (today's pending tickets)
  * 10:30 ET (after open + fills) — place trailing stops on new positions
  * 10:35 ET                       — sync from broker (pull fill prices back)
  * 16:15 ET (after close)        — run closeout (mark to market, log row)
  * 16:30 ET                       — refresh cards again (post-close data)

What it deliberately does NOT do:
  * Send BUY/SELL orders — fund.md §7 requires a human click for that.
  * Cancel orders — pulls capital back, never automate.
  * Switch active strategy — that's a policy change.

Idempotent: each job records its last-success date in
``~/.fund/scheduler_state.json`` and skips if already run today. Survives
restarts. Logs to ``~/.fund/scheduler.log`` + sends a macOS notification on
each run so you know what fired.

Run manually (foreground):
    python3 -m fund.scheduler --once       # run all due jobs once and exit
    python3 -m fund.scheduler --daemon     # loop forever, sleep 60s between checks

Or install as a launchd agent that survives logout / reboot:
    python3 -m fund.scheduler --install
    launchctl list | grep com.fund         # confirm running
    python3 -m fund.scheduler --uninstall
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:   # Py < 3.9, or missing tzdata
    _ET = timezone(timedelta(hours=-5))   # ET-ish fallback

_STATE_DIR = os.path.expanduser("~/.fund")
_STATE_PATH = os.path.join(_STATE_DIR, "scheduler_state.json")
_LOG_PATH = os.path.join(_STATE_DIR, "scheduler.log")
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


# --- jobs -----------------------------------------------------------------

@dataclass(frozen=True)
class Job:
    name: str                # short identifier (used in state file)
    hour: int                # ET hour (0-23)
    minute: int
    args: list               # ["python3", "-m", "fund.X", ...]
    description: str
    weekday_only: bool = True   # skip Sat/Sun
    requires_broker: bool = False  # if True and ALPACA creds missing, skip


JOBS: list[Job] = [
    Job(name="refresh_pre_open", hour=5, minute=30,
        args=["python3", "-m", "fund.cache_for_ui", "--source", "auto"],
        description="Refresh dashboard cards before market open"),
    Job(name="morning", hour=8, minute=0,
        args=["python3", "-m", "fund.morning", "--source", "auto", "--quiet"],
        description="Generate today's pending tickets"),
    Job(name="place_stops", hour=10, minute=30,
        args=["python3", "-m", "fund.place_stops", "--broker", "alpaca", "--yes"],
        description="Trailing stops on new broker positions",
        requires_broker=True),
    Job(name="sync_from_broker", hour=10, minute=35,
        args=["python3", "-m", "fund.sync_from_broker", "--broker", "alpaca", "--yes"],
        description="Pull broker fills + cash back to local state",
        requires_broker=True),
    Job(name="closeout", hour=16, minute=15,
        args=["python3", "-m", "fund.closeout", "--source", "auto", "--quiet"],
        description="Close out the day (mark-to-market, log row)"),
    Job(name="refresh_post_close", hour=16, minute=30,
        args=["python3", "-m", "fund.cache_for_ui", "--source", "auto"],
        description="Refresh dashboard cards after market close"),
]


# --- state ----------------------------------------------------------------

@dataclass
class SchedulerState:
    last_success: dict = field(default_factory=dict)   # name -> ISO date
    last_run: dict = field(default_factory=dict)       # name -> ISO datetime
    last_exit: dict = field(default_factory=dict)      # name -> int

    @classmethod
    def load(cls) -> "SchedulerState":
        if not os.path.exists(_STATE_PATH):
            return cls()
        try:
            with open(_STATE_PATH) as f:
                raw = json.load(f)
            return cls(**raw)
        except Exception:
            return cls()

    def save(self) -> None:
        os.makedirs(_STATE_DIR, exist_ok=True)
        with open(_STATE_PATH, "w") as f:
            json.dump({"last_success": self.last_success,
                       "last_run": self.last_run,
                       "last_exit": self.last_exit}, f, indent=2)


# --- runner ---------------------------------------------------------------

def _log(line: str) -> None:
    os.makedirs(_STATE_DIR, exist_ok=True)
    ts = datetime.now().isoformat(timespec="seconds")
    with open(_LOG_PATH, "a") as f:
        f.write(f"[{ts}] {line}\n")


def _notify(title: str, body: str) -> None:
    """macOS notification via osascript. Silent on non-mac."""
    if sys.platform != "darwin":
        return
    try:
        subprocess.run([
            "osascript", "-e",
            f'display notification "{body}" with title "{title}"',
        ], capture_output=True, timeout=5)
    except Exception:
        pass


def _et_now() -> datetime:
    return datetime.now(_ET)


def _due_today(job: Job, state: SchedulerState, now: datetime) -> bool:
    """Should this job run NOW (today, after its scheduled time, not yet done)?"""
    if job.weekday_only and now.weekday() >= 5:
        return False
    if job.requires_broker and not os.environ.get("ALPACA_API_KEY"):
        return False
    scheduled = now.replace(hour=job.hour, minute=job.minute,
                            second=0, microsecond=0)
    if now < scheduled:
        return False
    last_success = state.last_success.get(job.name)
    if last_success == now.date().isoformat():
        return False
    return True


def _run_job(job: Job, state: SchedulerState) -> None:
    """Run a single job, update state, log, notify on failure."""
    now = _et_now()
    _log(f"START {job.name}: {' '.join(job.args)}")
    state.last_run[job.name] = now.isoformat()
    try:
        proc = subprocess.run(job.args, cwd=_REPO_ROOT,
                              capture_output=True, text=True, timeout=240)
        exit_code = proc.returncode
    except Exception as e:
        _log(f"  CRASH {job.name}: {e}")
        state.last_exit[job.name] = -1
        _notify(f"fund/{job.name} crashed", str(e)[:200])
        state.save()
        return
    state.last_exit[job.name] = exit_code
    if exit_code == 0:
        state.last_success[job.name] = now.date().isoformat()
        _log(f"  OK    {job.name} (exit 0)")
        first_line = (proc.stdout or "").strip().split("\n")[0][:140]
        _notify(f"fund/{job.name} done", first_line or job.description)
    else:
        _log(f"  FAIL  {job.name} exit={exit_code}\n"
             f"        stderr: {(proc.stderr or '').strip()[:500]}")
        _notify(f"fund/{job.name} FAILED exit {exit_code}",
                (proc.stderr or proc.stdout or "")[:200])
    state.save()


def run_once() -> int:
    """Run every due job once. Returns the number of jobs that fired."""
    state = SchedulerState.load()
    now = _et_now()
    fired = 0
    for job in JOBS:
        if _due_today(job, state, now):
            _run_job(job, state)
            fired += 1
    return fired


def run_daemon(poll_seconds: int = 60) -> None:
    """Forever-loop. Checks every `poll_seconds` (default 60) whether any
    job is due. Designed for launchd to keep alive."""
    _log("scheduler daemon started")
    while True:
        try:
            run_once()
        except Exception as e:
            _log(f"daemon error: {e}")
        time.sleep(poll_seconds)


# --- launchd install ------------------------------------------------------

_PLIST_LABEL = "com.fund.scheduler"
_PLIST_PATH = os.path.expanduser(f"~/Library/LaunchAgents/{_PLIST_LABEL}.plist")


def _build_plist() -> str:
    python = sys.executable
    env_lines = []
    # Propagate the keys the jobs need from the current shell into the plist
    for k in ("ALPACA_API_KEY", "ALPACA_API_SECRET", "ALPACA_BASE_URL",
              "FUND_PORTFOLIO_PATH", "FUND_CONTACT_EMAIL"):
        v = os.environ.get(k)
        if v:
            env_lines.append(f"      <key>{k}</key><string>{v}</string>")
    env_block = ("    <key>EnvironmentVariables</key>\n    <dict>\n"
                 + "\n".join(env_lines) + "\n    </dict>") if env_lines else ""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{_PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
      <string>{python}</string>
      <string>-m</string>
      <string>fund.scheduler</string>
      <string>--daemon</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{_REPO_ROOT}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{_LOG_PATH}.stdout</string>
    <key>StandardErrorPath</key>
    <string>{_LOG_PATH}.stderr</string>
{env_block}
</dict>
</plist>
"""


def _install() -> int:
    os.makedirs(os.path.dirname(_PLIST_PATH), exist_ok=True)
    with open(_PLIST_PATH, "w") as f:
        f.write(_build_plist())
    # Unload first (in case it's already running with old config), then load
    subprocess.run(["launchctl", "unload", _PLIST_PATH], capture_output=True)
    r = subprocess.run(["launchctl", "load", _PLIST_PATH], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"launchctl load failed: {r.stderr or r.stdout}")
        return 2
    print(f"installed {_PLIST_LABEL} → {_PLIST_PATH}")
    print(f"logs: {_LOG_PATH}")
    print(f"check status: launchctl list | grep {_PLIST_LABEL}")
    return 0


def _uninstall() -> int:
    if os.path.exists(_PLIST_PATH):
        subprocess.run(["launchctl", "unload", _PLIST_PATH], capture_output=True)
        os.unlink(_PLIST_PATH)
        print(f"removed {_PLIST_PATH}")
    else:
        print(f"not installed (no {_PLIST_PATH})")
    return 0


def _status() -> int:
    state = SchedulerState.load()
    print(f"\n  {'job':<22} {'time':>6}  {'last success':>20}  {'last exit':>10}")
    print(f"  {'-' * 22} {'-' * 6}  {'-' * 20}  {'-' * 10}")
    for job in JOBS:
        sched = f"{job.hour:02d}:{job.minute:02d}"
        ok = state.last_success.get(job.name, "—")
        exit_code = state.last_exit.get(job.name, "—")
        print(f"  {job.name:<22} {sched:>6}  {ok:>20}  {str(exit_code):>10}")
    print(f"\n  log: {_LOG_PATH}")
    if os.path.exists(_PLIST_PATH):
        print(f"  launchd installed: {_PLIST_PATH}")
    else:
        print(f"  launchd NOT installed (run --install)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Autonomous routine for fund/.")
    grp = ap.add_mutually_exclusive_group()
    grp.add_argument("--once", action="store_true",
                     help="run every due job once and exit")
    grp.add_argument("--daemon", action="store_true",
                     help="loop forever, sleep between checks")
    grp.add_argument("--install", action="store_true",
                     help="install as macOS launchd agent")
    grp.add_argument("--uninstall", action="store_true",
                     help="remove the launchd agent")
    grp.add_argument("--status", action="store_true",
                     help="show last-success per job + install status")
    args = ap.parse_args()
    if args.install:
        return _install()
    if args.uninstall:
        return _uninstall()
    if args.status:
        return _status()
    if args.daemon:
        run_daemon()
        return 0
    n = run_once()
    print(f"{n} job(s) fired.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
