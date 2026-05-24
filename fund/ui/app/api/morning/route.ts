/**
 * POST /api/morning  — generate today's pending tickets for the active strategy.
 * Body: { source?: "auto" | "real" | "synthetic", asOf?: "YYYY-MM-DD" }
 */
import { NextRequest, NextResponse } from "next/server";
import { runPython } from "@/lib/run_py";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(req: NextRequest) {
  const { source = "auto", asOf = "" } = await req.json().catch(() => ({}));
  const args = ["-m", "fund.morning", "--source", source];
  if (asOf) args.push("--as-of", asOf);
  const result = await runPython(args, 240_000);
  return NextResponse.json(result);
}
