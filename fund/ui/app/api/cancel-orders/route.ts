/**
 * POST /api/cancel-orders
 * Body: { broker: "alpaca"|"ibkr", dryRun?: boolean }
 *
 * Cancels every OPEN order at the broker. Doesn't touch positions or local
 * state — pair with /api/sync-from-broker after if you need to reset both.
 */
import { NextRequest, NextResponse } from "next/server";
import { runPython } from "@/lib/run_py";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(req: NextRequest) {
  const { broker, dryRun } = (await req.json().catch(() => ({}))) as {
    broker?: string;
    dryRun?: boolean;
  };
  if (broker !== "alpaca" && broker !== "ibkr") {
    return NextResponse.json(
      { error: "broker must be 'alpaca' or 'ibkr'" },
      { status: 400 }
    );
  }
  const args = ["-m", "fund.cancel_orders", "--broker", broker];
  if (dryRun) args.push("--dry-run");
  else args.push("--yes");
  const result = await runPython(args, 30_000);
  return NextResponse.json(result);
}
