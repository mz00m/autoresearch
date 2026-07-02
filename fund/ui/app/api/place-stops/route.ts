/**
 * POST /api/place-stops
 * Body: { broker: "alpaca"|"ibkr", trail?: number, dryRun?: boolean }
 *
 * Places a GTC trailing-stop SELL at the broker for every held position
 * that doesn't already have one. Default trail = 15%.
 */
import { NextRequest, NextResponse } from "next/server";
import { runPython } from "@/lib/run_py";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(req: NextRequest) {
  const { broker, trail = 15, dryRun } = (await req.json().catch(() => ({}))) as {
    broker?: string;
    trail?: number;
    dryRun?: boolean;
  };
  if (broker !== "alpaca" && broker !== "ibkr") {
    return NextResponse.json(
      { error: "broker must be 'alpaca' or 'ibkr'" },
      { status: 400 }
    );
  }
  const args = ["-m", "fund.place_stops", "--broker", broker,
                "--trail", String(trail)];
  if (dryRun) args.push("--dry-run");
  else args.push("--yes");
  const result = await runPython(args, 60_000);
  return NextResponse.json(result);
}
