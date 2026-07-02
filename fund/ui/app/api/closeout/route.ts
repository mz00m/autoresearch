/**
 * POST /api/closeout  — fill pending tickets at today's close, mark to market.
 * Body: { source?, asOf?, slippageBps?: number }
 */
import { NextRequest, NextResponse } from "next/server";
import { runPython } from "@/lib/run_py";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(req: NextRequest) {
  const { source = "auto", asOf = "", slippageBps = 5 } =
    await req.json().catch(() => ({}));
  const args = [
    "-m", "fund.closeout",
    "--source", source,
    "--slippage-bps", String(slippageBps),
  ];
  if (asOf) args.push("--as-of", asOf);
  const result = await runPython(args, 240_000);
  return NextResponse.json(result);
}
