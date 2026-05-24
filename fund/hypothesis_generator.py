"""hypothesis_generator.py — programmatic grid for autoresearch cycles.

Produces a few dozen (strategy, params) variants the proper_research module
runs through the OOS + deflated-Sharpe protocol. Rather than testing one
strategy with hand-picked params, we sweep across reasonable parameter
ranges + combine compatible variants. The point isn't to find a magic
combination — it's to give the deflation correction a real workout, so
any "keep" verdict has earned the multiple-testing penalty.
"""

from __future__ import annotations


def momentum_variants() -> list[tuple[str, dict, str]]:
    """Cross-sectional + skip-month momentum across N, lookback windows."""
    out: list[tuple[str, dict, str]] = []
    for n in (1, 2, 3):
        for lb in (63, 126, 189, 252):
            out.append(("top_n_momentum",
                        {"n": n, "lookback_days": lb},
                        f"top{n} {lb}d"))
    for n in (1, 2, 3):
        for long_lb in (126, 189, 252):
            for skip in (10, 21):
                out.append(("skip_month_momentum",
                            {"n": n, "long_lookback": long_lb, "skip_lookback": skip},
                            f"skip-mom n={n} {long_lb}-{skip}"))
    return out


def trend_variants() -> list[tuple[str, dict, str]]:
    """Time-series momentum + MA crossover sweeps."""
    out: list[tuple[str, dict, str]] = []
    for lb in (63, 126, 189, 252):
        out.append(("time_series_momentum", {"lookback_days": lb}, f"tsmom {lb}d"))
    for fast, slow in ((20, 100), (50, 150), (50, 200), (100, 200)):
        out.append(("ma_crossover", {"fast": fast, "slow": slow},
                    f"MA {fast}/{slow}"))
    return out


def defensive_variants() -> list[tuple[str, dict, str]]:
    """Risk-parity sweeps + the fixed-weight defensive bench."""
    out: list[tuple[str, dict, str]] = [
        ("sixty_forty", {}, "60/40"),
        ("permanent_portfolio", {}, "Permanent Portfolio"),
        ("all_weather", {}, "All-Weather"),
        ("rp_crisis_hedge", {}, "RP + 15% TLT"),
    ]
    for vw in (21, 63, 126):
        out.append(("risk_parity", {"vol_window": vw}, f"risk-parity {vw}d"))
    for sma in (100, 150, 200, 250):
        out.append(("faber_gtaa", {"sma_window": sma}, f"Faber SMA{sma}"))
    return out


def factor_variants() -> list[tuple[str, dict, str]]:
    """Other documented signals."""
    out: list[tuple[str, dict, str]] = [
        ("trend_carry", {}, "trend+carry"),
    ]
    for n in (2, 3, 4):
        for vw in (63, 126):
            out.append(("low_vol", {"n": n, "vol_window": vw},
                        f"low-vol n={n} {vw}d"))
    return out


def full_grid() -> list[tuple[str, dict, str]]:
    """Union of all variant generators — the full hypothesis set."""
    seen = set()
    out: list[tuple[str, dict, str]] = []
    for batch in (momentum_variants(), trend_variants(),
                  defensive_variants(), factor_variants()):
        for spec in batch:
            key = (spec[0], tuple(sorted(spec[1].items())))
            if key in seen:
                continue
            seen.add(key)
            out.append(spec)
    return out


if __name__ == "__main__":
    g = full_grid()
    print(f"{len(g)} hypotheses:")
    for name, params, label in g:
        print(f"  {label:<28}  {name}({params})")
