/**
 * POST /api/refresh-cache  — recompute ui_cache.json (recs + sell + tax +
 * regime + drift) so the dashboard cards reflect the latest data.
 */
import { NextRequest, NextResponse } from "next/server";
import { runPython } from "@/lib/run_py";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(req: NextRequest) {
  const { source = "auto", asOf = "" } = await req.json().catch(() => ({}));
  const args = ["-m", "fund.cache_for_ui", "--source", source];
  if (asOf) args.push("--as-of", asOf);
  const result = await runPython(args, 240_000);
  return NextResponse.json(result);
}
