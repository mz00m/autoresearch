/**
 * POST /api/sync-from-broker
 * Body: { broker: "alpaca"|"ibkr", dryRun?: boolean }
 *
 * Pulls broker account snapshot, overwrites portfolio_state.json (or just
 * previews if dryRun). Never writes to the broker. Pending tickets get
 * cleared because they were sized against the old book.
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
  const args = ["-m", "fund.sync_from_broker", "--broker", broker];
  if (dryRun) args.push("--dry-run");
  else args.push("--yes");
  const result = await runPython(args, 60_000);
  return NextResponse.json(result);
}
