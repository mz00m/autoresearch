"""Run every test module in fund/tests. One-line summary + nonzero exit on fail."""

from __future__ import annotations

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main() -> int:
    files = sorted(
        f for f in os.listdir(HERE)
        if f.startswith("test_") and f.endswith(".py")
    )
    total_pass = total_run = 0
    failures: list[str] = []
    for f in files:
        path = os.path.join(HERE, f)
        out = subprocess.run([sys.executable, path], capture_output=True, text=True)
        # last line of each file is "<n>/<n> tests passed"
        last = (out.stdout.strip().splitlines() or [""])[-1]
        try:
            passed_s, _, rest = last.partition("/")
            total_s = rest.split()[0]
            p, t = int(passed_s), int(total_s)
        except (ValueError, IndexError):
            failures.append(f"{f}: could not parse output")
            print(f"  ?? {f}\n{out.stdout}\n{out.stderr}")
            continue
        total_pass += p
        total_run += t
        flag = "OK" if p == t else "XX"
        print(f"  [{flag}] {f}  {p}/{t}")
        if p != t:
            failures.append(f"{f}: {p}/{t}")
            print(out.stdout)

    print(f"\n{total_pass}/{total_run} tests passed across {len(files)} files")
    if failures:
        print("FAILED:", "; ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
