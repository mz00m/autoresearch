"""coach.py — synthesize verdict + drift + tax + wash into ONE recommendation.

Decision says "watch", Drift says "drifted", Tax says "$X harvestable losses",
Wash says "USO blocked for 12 more days". Each card on the Today page tells
you *something* — but you still have to interpret. This module is the
translator: given the bundle of signals, what's the *one* next action?

The synthesis is rule-based (no LLM in the trading loop, per fund.md §7).
The recommendations are deliberately conservative — when in doubt, say
"hold and watch", never "rotate harder."

Output: one ``CoachReport`` with severity + a single human-readable action.
The dashboard puts this at the very top of the Today page so the user can
make a decision without doing the synthesis themselves.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CoachReport:
    severity: str           # informational | watch | action | urgent
    headline: str           # 1-line verdict shown big
    rationale: str          # 1-2 sentences explaining why
    next_action: str        # the single concrete next step


def synthesize(
    *,
    decision_verdict: str,         # ok | watch | iterate
    decision_excess_pp: float,     # trailing excess vs SPY in pp
    drift_verdict: str | None,     # in_band | drifting | drifted
    drift_reason: str | None,
    tax_net_total: float,
    tax_net_long_term: float,
    wash_warnings: int,
    has_pending_tickets: bool,
    active_strategy: str,
    current_drawdown: float,
) -> CoachReport:
    """Return one consolidated action card driven by all the signals."""

    # 1. URGENT — wash sale active right now AND user about to send tickets
    if has_pending_tickets and wash_warnings > 0:
        return CoachReport(
            severity="urgent",
            headline=f"Wash-sale risk on {wash_warnings} pending BUY(s)",
            rationale="One or more pending tickets would buy a symbol you "
                      "sold at a loss within the last 30 days. Sending them "
                      "now voids the loss deduction (IRC §1091).",
            next_action="Defer those tickets until the wash window clears, "
                        "or send only the unaffected ones.",
        )

    # 2. URGENT — drifted AND iterate verdict converge: strategy is broken
    if decision_verdict == "iterate" and drift_verdict == "drifted":
        return CoachReport(
            severity="urgent",
            headline="Strategy is failing live",
            rationale=f"Trailing 20d excess {decision_excess_pp:+.1f}pp AND "
                      f"live distribution significantly off backtest. "
                      f"{drift_reason or ''}",
            next_action="Switch the active strategy. Run Compare to see "
                        "which bench candidate would have led the same "
                        "window, then use the Strategy Picker to switch.",
        )

    # 3. ACTION — drift fires alone (decision still OK)
    if drift_verdict == "drifted":
        return CoachReport(
            severity="action",
            headline=f"{active_strategy} live behavior diverges from backtest",
            rationale=drift_reason or "Live mean return is statistically off "
                                       "the backtest distribution.",
            next_action="Investigate before adding capital. Common causes: "
                        "regime change, hidden costs, or a data error. "
                        "Don't switch yet — confirm with another 10-20 days.",
        )

    # 4. ACTION — iterate fires alone
    if decision_verdict == "iterate":
        return CoachReport(
            severity="action",
            headline=f"{active_strategy} is being outpaced",
            rationale=f"Trailing excess {decision_excess_pp:+.1f}pp vs SPY "
                      f"over the last 20 days.",
            next_action="Run Compare to see what would have done better, "
                        "then consider switching via the Strategy Picker.",
        )

    # 5. WATCH — tax harvesting opportunity worth surfacing
    if tax_net_total < -200 and tax_net_long_term < 0:
        return CoachReport(
            severity="watch",
            headline=f"${abs(tax_net_total):,.0f} in harvestable losses YTD",
            rationale=f"You have ${abs(tax_net_long_term):,.0f} of net "
                      f"long-term losses already realized. If you intend to "
                      f"sell positions with embedded gains, time the sales "
                      f"to offset.",
            next_action="No immediate action — keep in mind when next "
                        "rotation generates SELL tickets.",
        )

    # 6. WATCH — drawdown alone
    if current_drawdown > 0.10:
        return CoachReport(
            severity="watch",
            headline=f"Drawdown -{current_drawdown * 100:.1f}% from peak",
            rationale="Below 10% peak-to-trough but above the on-track "
                      "threshold.",
            next_action="Check the verdict reasons; if both decision and "
                        "drift stay in band, hold the line.",
        )

    # 7. WATCH — decision verdict
    if decision_verdict == "watch":
        return CoachReport(
            severity="watch",
            headline=f"{active_strategy} on watch",
            rationale=f"Trailing excess {decision_excess_pp:+.1f}pp — early "
                      f"signal, not yet actionable.",
            next_action="Monitor for another 10-20 days. If excess stays "
                        "negative and hit rate falls below 40%, switch.",
        )

    # 8. INFORMATIONAL — all green; surface pending tickets if any
    if has_pending_tickets:
        return CoachReport(
            severity="informational",
            headline="Pending tickets ready to send",
            rationale="Verdict and drift both in band — strategy is "
                      "performing as expected.",
            next_action="Review the recommendations below; click Dry-run "
                        "to preview, then Send orders to fire at the broker.",
        )

    return CoachReport(
        severity="informational",
        headline="Nothing to do today",
        rationale=f"{active_strategy} is on track, no drift, no pending "
                  f"tickets, no wash-sale conflicts.",
        next_action="Run Morning when you're ready for tomorrow's allocation.",
    )
