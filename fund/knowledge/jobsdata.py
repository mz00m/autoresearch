"""jobsdata.ai connector — pull AI-investment-relevant facts into the thesis layer.

Reads from Matt's jobsdata project at ~/jobsdata/ and surfaces:
  * Token cost decline (Stanford HAI: 280x in 18 months)
  * Hyperscaler AI capex curve (JPMorgan CEO letter 2026: $450B → $725B YoY)
  * Industry displacement adoption curves (9 sectors with confidence bounds)
  * Tier-1 source citations (NBER, AER, BLS, etc.)

Then produces (a) a thesis brief, (b) recommended thesis records for the
AI-exposed positions in our universe (TQQQ, SOXL, QQQ, URA — and noting
the indirect connection for USO / energy via datacenter power demand).

Pure-stdlib reader. The connector is read-only; we never write to jobsdata.

  python3 -m fund.knowledge.jobsdata --brief
  python3 -m fund.knowledge.jobsdata --seed-theses   # auto-populate fund.thesis
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

JOBSDATA_ROOT = Path(os.environ.get(
    "JOBSDATA_ROOT", str(Path.home() / "jobsdata")))

DISPLACEMENT_DIR = JOBSDATA_ROOT / "src/data/predictions/displacement"
ADOPTION_DIR     = JOBSDATA_ROOT / "src/data/predictions/adoption"
WAGES_DIR        = JOBSDATA_ROOT / "src/data/predictions/wages"
METHODOLOGY_MD   = JOBSDATA_ROOT / "wiki/task-visualizer/methodology.md"
DIMON_LETTER     = JOBSDATA_ROOT / "wiki/sources/dimon-jpmorgan-ceo-letter-2026.md"
SOURCES_JSON     = JOBSDATA_ROOT / "src/data/confirmed-sources.json"


# --- readers ---------------------------------------------------------------

@dataclass
class Prediction:
    slug: str
    title: str
    description: str
    category: str
    unit: str
    current_value: float
    time_horizon: str
    latest_date: Optional[str] = None
    latest_low: Optional[float] = None
    latest_high: Optional[float] = None
    source_ids_latest: list[str] = None  # type: ignore[assignment]


def _read_prediction(path: Path) -> Optional[Prediction]:
    try:
        d = json.loads(path.read_text())
    except Exception:
        return None
    history = d.get("history") or []
    latest = max(history, key=lambda h: h.get("date", ""), default={})
    return Prediction(
        slug=d.get("slug", path.stem),
        title=d.get("title", ""),
        description=d.get("description", ""),
        category=d.get("category", ""),
        unit=d.get("unit", ""),
        current_value=float(d.get("currentValue", 0.0) or 0.0),
        time_horizon=d.get("timeHorizon", ""),
        latest_date=latest.get("date"),
        latest_low=latest.get("confidenceLow"),
        latest_high=latest.get("confidenceHigh"),
        source_ids_latest=list(latest.get("sourceIds", [])),
    )


def all_displacement() -> list[Prediction]:
    if not DISPLACEMENT_DIR.exists():
        return []
    return sorted(
        (p for p in (_read_prediction(f) for f in DISPLACEMENT_DIR.glob("*.json"))
         if p is not None),
        key=lambda p: -p.current_value,
    )


def all_adoption() -> list[Prediction]:
    if not ADOPTION_DIR.exists():
        return []
    return [p for p in (_read_prediction(f) for f in ADOPTION_DIR.glob("*.json"))
            if p is not None]


def _read_methodology_excerpt() -> str:
    """Pull the token-cost + cost-decline block. Falls back to empty string."""
    if not METHODOLOGY_MD.exists():
        return ""
    text = METHODOLOGY_MD.read_text()
    # Heuristic: grab the first 80 lines, which contain the cost tables +
    # decline-rate citations in the current methodology doc.
    return "\n".join(text.split("\n")[:80])


def _read_dimon_excerpt() -> str:
    """First ~60 lines of the JPMorgan CEO letter excerpt — contains the
    $450B → $725B hyperscaler capex jump."""
    if not DIMON_LETTER.exists():
        return ""
    text = DIMON_LETTER.read_text()
    return "\n".join(text.split("\n")[:60])


def _source(source_id: str) -> Optional[dict]:
    """Look up a source by id in confirmed-sources.json."""
    if not SOURCES_JSON.exists():
        return None
    try:
        rows = json.loads(SOURCES_JSON.read_text())
    except Exception:
        return None
    if isinstance(rows, dict) and "sources" in rows:
        rows = rows["sources"]
    if not isinstance(rows, list):
        return None
    for r in rows:
        if r.get("id") == source_id:
            return r
    return None


# --- the brief --------------------------------------------------------------

def thesis_brief() -> str:
    """Human-readable summary of the most thesis-relevant facts from jobsdata."""
    if not JOBSDATA_ROOT.exists():
        return f"# jobsdata.ai brief\n\n*JOBSDATA_ROOT={JOBSDATA_ROOT} not found.*"

    parts: list[str] = []
    parts.append("# jobsdata.ai brief — AI investment thesis context")
    parts.append(f"_Pulled {date.today().isoformat()} from {JOBSDATA_ROOT}_\n")

    parts.append("## 1. Token cost decline (the AI-compute deflation engine)\n")
    methodology = _read_methodology_excerpt()
    if methodology:
        # Try to surface the key cost lines if present
        for line in methodology.split("\n"):
            if any(k in line.lower() for k in [
                "280x", "stanford hai", "epoch", "a16z", "llmflation",
                "$0.25/1m", "$2/1m", "$10/1m", "sequoia"
            ]):
                parts.append(f"  > {line.strip()}")
    else:
        parts.append("  *(methodology.md not found)*")

    parts.append("\n## 2. Hyperscaler AI capex (the demand curve)\n")
    dimon = _read_dimon_excerpt()
    if dimon:
        for line in dimon.split("\n"):
            if any(k in line for k in ["$450B", "$725B", "capex", "Capex",
                                       "hyperscaler", "Hyperscaler",
                                       "61%", "AI infrastructure"]):
                parts.append(f"  > {line.strip()}")
    else:
        parts.append("  *(JPMorgan CEO letter excerpt not found)*")

    parts.append("\n## 3. Sector displacement curves\n")
    disp = all_displacement()
    if disp:
        parts.append("  Latest projections by sector (% of jobs displaced by 2030):\n")
        for p in disp[:10]:
            band = ""
            if p.latest_low is not None and p.latest_high is not None:
                band = f" [conf {p.latest_low:.1f}–{p.latest_high:.1f}]"
            parts.append(f"  - **{p.title}** — {p.current_value:.1f}%{band}")
    else:
        parts.append("  *(no displacement files found)*")

    parts.append("\n## 4. Adoption curves\n")
    adopt = all_adoption()
    if adopt:
        for p in adopt[:6]:
            parts.append(f"  - **{p.title}** — currently {p.current_value:.1f}{p.unit}"
                         f" ({p.time_horizon})")
    else:
        parts.append("  *(no adoption files found)*")

    parts.append("\n## 5. What this means for investing\n")
    parts.append(
        "  - **AI compute demand is structural.** $725B/yr hyperscaler capex\n"
        "    (up 61% YoY) is multi-year visibility for hyperscaler suppliers\n"
        "    — semis (SOXL/SOXX), networking, datacenter REITs, power utilities.\n"
        "  - **The cost decline is the catalyst.** 280x token cost compression\n"
        "    in 18 months means every economically-marginal use case becomes\n"
        "    viable; deployment volume grows faster than per-token cost falls.\n"
        "  - **Adoption is gated by institutional lag, not capability.** That\n"
        "    means the AI productivity narrative likely has 2-5 years to run\n"
        "    even if model capability plateaued today.\n"
        "  - **Energy is the constraint.** Datacenter buildout requires\n"
        "    massive baseload power → nuclear renaissance (URA) + natural gas\n"
        "    (some USO/XLE exposure indirect via gen capacity).\n"
    )
    return "\n".join(parts)


# --- thesis seeds -----------------------------------------------------------

def recommended_theses() -> list[dict]:
    """For each AI-thesis-relevant symbol in our universe, return a starter
    thesis grounded in jobsdata facts. The user can edit/refine before
    committing via fund.thesis.add()."""
    # Pull the capex number if available so the catalyst is concrete
    dimon = _read_dimon_excerpt()
    capex_line = next((ln.strip() for ln in dimon.split("\n")
                       if "$725B" in ln or "$725" in ln), "")
    capex_phrase = capex_line if capex_line else (
        "JPMorgan CEO letter Jan 2026: hyperscaler AI capex $450B (2025) → $725B (2026), +61% YoY")

    out = [
        {
            "symbol": "TQQQ",
            "catalyst": (
                f"Hyperscaler AI capex compounding ({capex_phrase}). "
                "Token-cost decline (~280x / 18mo per Stanford HAI 2025) means "
                "deployment volume scales faster than per-token cost falls — "
                "net-revenue tailwind for Nasdaq tech leaders. 3x leverage on the trend."
            ),
            "kill_switch": (
                "Hyperscaler quarterly capex guidance cut by >15% vs prior "
                "quarter, OR Stanford HAI cost-decline series reverses for 2+ "
                "consecutive quarters, OR antitrust/regulatory action targeting "
                "cloud/AI consolidation."
            ),
            "horizon": "12-18 months — re-evaluate at each Big-Tech earnings cycle",
            "confidence": 4,
            "author": "matt (auto-seeded from jobsdata.ai)",
        },
        {
            "symbol": "SOXL",
            "catalyst": (
                "Semiconductor demand pulled by AI compute buildout (same "
                f"hyperscaler capex curve: {capex_phrase}). NVDA/TSMC/AVGO "
                "supply chain has multi-year backlog visibility. 3x leverage "
                "captures the bull case but path-decays in choppy markets."
            ),
            "kill_switch": (
                "China tech-export restrictions widen, OR a major chip "
                "oversupply event (DRAM/HBM glut), OR TSMC capex guide cut, "
                "OR a recession that delays hyperscaler buildout."
            ),
            "horizon": "12-18 months — reassess at each TSMC capex announcement",
            "confidence": 4,
            "author": "matt (auto-seeded from jobsdata.ai)",
        },
        {
            "symbol": "QQQ",
            "catalyst": (
                "Same AI/hyperscaler tailwind as TQQQ but unlevered. "
                f"Per jobsdata: {capex_phrase}. Adoption is institutionally "
                "gated (Rogers/Griliches diffusion lags) so the productivity "
                "narrative likely has 2-5 years to run even if model "
                "capability plateaued today."
            ),
            "kill_switch": (
                "Same as TQQQ but at half the urgency (no leverage decay)."
            ),
            "horizon": "18-36 months",
            "confidence": 4,
            "author": "matt (auto-seeded from jobsdata.ai)",
        },
        {
            "symbol": "URA",
            "catalyst": (
                "AI datacenter buildout is baseload-power-constrained. "
                "Hyperscalers (Amazon, Microsoft, Meta) have publicly committed "
                "to nuclear PPAs in 2024-2025. Uranium spot price is up sharply "
                "and miners haven't fully repriced the structural demand shift. "
                "Indirect read on the same hyperscaler capex curve."
            ),
            "kill_switch": (
                "A major nuclear incident reversing public sentiment, OR "
                "hyperscaler PPA contracts get cancelled, OR a cheap "
                "renewables-plus-storage breakthrough that obviates baseload."
            ),
            "horizon": "24-48 months — long supply build cycle",
            "confidence": 3,
            "author": "matt (auto-seeded from jobsdata.ai)",
        },
        {
            "symbol": "USO",
            "catalyst": (
                "Geopolitical risk premium (Iran/Mideast tensions) layered on "
                "top of structural underinvestment in oil supply since 2014. "
                "Indirect AI connection: datacenter power demand has lifted "
                "natural gas + crude (some power gen is gas-fired). The trade "
                "is primarily geopolitical, not AI-thesis."
            ),
            "kill_switch": (
                "Iran nuclear deal signed, OR OPEC+ adds >1mb/d to quotas, "
                "OR a global recession dropping demand by >2mb/d."
            ),
            "horizon": "3-6 months, reassess at each OPEC + Iran-talks update",
            "confidence": 2,
            "author": "matt (auto-seeded from jobsdata.ai)",
        },
    ]
    return out


# --- CLI --------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="jobsdata.ai → fund.thesis bridge.")
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--brief", action="store_true",
                     help="print thesis brief to stdout (markdown)")
    grp.add_argument("--seed-theses", action="store_true",
                     help="add recommended starter theses via fund.thesis")
    grp.add_argument("--list-theses", action="store_true",
                     help="show the auto-seed recommendations (no writes)")
    grp.add_argument("--out", default="",
                     help="write JSON of {brief, recommended_theses} to path")
    args = ap.parse_args()

    if args.brief:
        print(thesis_brief())
        return 0
    if args.list_theses:
        for t in recommended_theses():
            print(f"\n{t['symbol']} — conviction {t['confidence']}/5  "
                  f"({t['horizon']})")
            print(f"  CATALYST: {t['catalyst']}")
            print(f"  KILL:     {t['kill_switch']}")
        return 0
    if args.seed_theses:
        from fund.thesis import Thesis, active_for, add
        added = 0
        skipped = 0
        for t in recommended_theses():
            if active_for(t["symbol"]):
                print(f"  ~ {t['symbol']}: already has an active thesis, skip")
                skipped += 1
                continue
            add(Thesis(symbol=t["symbol"], catalyst=t["catalyst"],
                       kill_switch=t["kill_switch"], horizon=t["horizon"],
                       confidence=t["confidence"], author=t["author"]))
            print(f"  + {t['symbol']}: seeded ({t['confidence']}/5)")
            added += 1
        print(f"\n{added} seeded, {skipped} skipped (already had active).")
        return 0
    if args.out:
        data = {"brief": thesis_brief(),
                "recommended_theses": recommended_theses()}
        Path(args.out).write_text(json.dumps(data, indent=2))
        print(f"wrote {args.out}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
