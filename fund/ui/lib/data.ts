/**
 * Server-side readers for the fund/ Python ops state.
 * The UI is a viewer — it never writes to these files. Python owns them.
 */
import { promises as fs } from "fs";
import path from "path";

// fund/ui/ sits inside fund/, so all artifacts are one dir up
const FUND_ROOT = path.resolve(process.cwd(), "..");
const STATE_PATH = path.join(FUND_ROOT, "portfolio_state.json");
const LOG_PATH = path.join(FUND_ROOT, "daily_log.tsv");

export type Position = { qty: number; avg_cost: number };

export type Ticket = {
  ticket_id: string;
  created: string;
  symbol: string;
  side: "BUY" | "SELL";
  qty: number;
  ref_price: number;
  rationale: string;
  risk_max_loss: number;
  status: "pending" | "filled" | "rejected" | "expired";
  fill_date: string;
  fill_price: number;
  slippage_bps: number;
};

export type EquityPoint = {
  date: string;
  cash: number;
  position_value: number;
  equity: number;
};

export type Portfolio = {
  principal: number;
  cash: number;
  positions: Record<string, Position>;
  history: EquityPoint[];
  pending: Ticket[];
  filled: Ticket[];
  active_strategy: string;
  active_strategy_params: Record<string, unknown>;
  inception: string;
  last_marked: string;
};

export type DailyRow = {
  date: string;
  strategy: string;
  cash: number;
  position_value: number;
  equity: number;
  day_return: number;
  cum_return: number;
  benchmark_cum_return: number | null;
  drawdown: number;
  n_filled: number;
  n_rejected: number;
  n_expired: number;
  note: string;
};

export async function readPortfolio(): Promise<Portfolio | null> {
  try {
    const raw = await fs.readFile(STATE_PATH, "utf8");
    return JSON.parse(raw) as Portfolio;
  } catch (e: unknown) {
    if ((e as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw e;
  }
}

export async function readDailyLog(): Promise<DailyRow[]> {
  let raw: string;
  try {
    raw = await fs.readFile(LOG_PATH, "utf8");
  } catch (e: unknown) {
    if ((e as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw e;
  }
  const lines = raw.trim().split("\n");
  if (lines.length < 2) return [];
  const header = lines[0].split("\t");
  return lines.slice(1).map((line) => {
    const cells = line.split("\t");
    const r: Record<string, string> = {};
    header.forEach((h, i) => (r[h] = cells[i] ?? ""));
    return {
      date: r.date,
      strategy: r.strategy,
      cash: parseFloat(r.cash || "0"),
      position_value: parseFloat(r.position_value || "0"),
      equity: parseFloat(r.equity || "0"),
      day_return: parseFloat(r.day_return || "0"),
      cum_return: parseFloat(r.cum_return || "0"),
      benchmark_cum_return: r.benchmark_cum_return
        ? parseFloat(r.benchmark_cum_return)
        : null,
      drawdown: parseFloat(r.drawdown || "0"),
      n_filled: parseInt(r.n_filled || "0", 10),
      n_rejected: parseInt(r.n_rejected || "0", 10),
      n_expired: parseInt(r.n_expired || "0", 10),
      note: r.note || "",
    };
  });
}

/** Trailing-N decision signal mirroring fund/decision.py. */
export type Decision = {
  n_days: number;
  trailing_return: number;
  trailing_benchmark: number;
  trailing_excess: number;
  hit_rate: number;
  worst_day: number;
  current_drawdown: number;
  verdict: "ok" | "watch" | "iterate";
  reason: string;
};

export function computeDecision(rows: DailyRow[], windowDays = 20): Decision {
  if (rows.length === 0) {
    return {
      n_days: 0,
      trailing_return: 0,
      trailing_benchmark: 0,
      trailing_excess: 0,
      hit_rate: 0,
      worst_day: 0,
      current_drawdown: 0,
      verdict: "ok",
      reason: "No track record yet — run the loop for a few days first.",
    };
  }
  const window = rows.slice(-windowDays);
  const portRets = window.map((r) => r.day_return);
  // reconstruct daily bench returns from cum_return deltas
  let priorCum =
    rows.length > windowDays
      ? rows[rows.length - windowDays - 1].benchmark_cum_return ?? 0
      : 0;
  const benchRets = window.map((r) => {
    const cur = r.benchmark_cum_return ?? priorCum;
    const prev = 1 + priorCum;
    priorCum = cur;
    return prev > 0 ? (1 + cur) / prev - 1 : 0;
  });
  const compound = (xs: number[]) => xs.reduce((a, x) => a * (1 + x), 1) - 1;
  const trailingPort = compound(portRets);
  const trailingBench = compound(benchRets);
  const excess = trailingPort - trailingBench;
  const paired = portRets.map((p, i) => [p, benchRets[i]] as const);
  const hits = paired.filter(([p, b]) => p > b).length;
  const hitRate = paired.length > 0 ? hits / paired.length : 0;
  const worst = portRets.length > 0 ? Math.min(...portRets) : 0;
  const dd = window[window.length - 1].drawdown;
  const excessPp = excess * 100;
  let verdict: Decision["verdict"];
  let reason: string;
  if (excessPp <= -3 && hitRate < 0.4 && window.length >= 20) {
    verdict = "iterate";
    reason = `Trailing ${window.length}d excess ${excessPp.toFixed(1)}pp with ${(
      hitRate * 100
    ).toFixed(0)}% hit rate — strategy is being outpaced; consider switching.`;
  } else if (excessPp <= -1 || dd >= 0.08) {
    verdict = "watch";
    const bits: string[] = [];
    if (excessPp <= -1) bits.push(`trailing ${window.length}d ${excessPp.toFixed(1)}pp vs SPY`);
    if (dd >= 0.08) bits.push(`drawdown -${(dd * 100).toFixed(1)}%`);
    reason = `Watching: ${bits.join("; ")}.`;
  } else {
    verdict = "ok";
    reason = `On track — ${window.length}d excess ${excessPp.toFixed(
      1
    )}pp, hit rate ${(hitRate * 100).toFixed(0)}%, drawdown -${(dd * 100).toFixed(
      1
    )}%.`;
  }
  return {
    n_days: window.length,
    trailing_return: trailingPort,
    trailing_benchmark: trailingBench,
    trailing_excess: excess,
    hit_rate: hitRate,
    worst_day: worst,
    current_drawdown: dd,
    verdict,
    reason,
  };
}

export function formatMoney(n: number) {
  return n.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

export function formatPct(n: number, digits = 2) {
  const sign = n > 0 ? "+" : "";
  return `${sign}${(n * 100).toFixed(digits)}%`;
}

export function formatPp(n: number, digits = 2) {
  const sign = n > 0 ? "+" : "";
  return `${sign}${(n * 100).toFixed(digits)}pp`;
}
