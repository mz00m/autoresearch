/**
 * POST /api/switch-strategy  — change active strategy in portfolio_state.json.
 * Body: { strategy: string, params?: object }
 * Does NOT generate tickets; run /api/morning after to rotate.
 */
import { NextRequest, NextResponse } from "next/server";
import { runPython } from "@/lib/run_py";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

// adaptive + stable_adaptive deliberately omitted — empirically poor (see
// fund.honest_test). They remain callable via the registry for diagnostics
// but the UI doesn't let you switch into them.
const ALLOWED = new Set([
  "sixty_forty", "dual_momentum", "risk_parity",
  "top_n_momentum", "ma_crossover", "leveraged_momentum",
  "regime_aware", "multi",
]);

export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => ({}))) as {
    strategy?: string;
    params?: Record<string, unknown>;
  };
  if (!body.strategy || !ALLOWED.has(body.strategy)) {
    return NextResponse.json(
      { error: `strategy must be one of: ${[...ALLOWED].join(", ")}` },
      { status: 400 }
    );
  }
  const args = [
    "-m", "fund.portfolio", "switch",
    "--strategy", body.strategy,
    "--params", JSON.stringify(body.params ?? {}),
  ];
  const result = await runPython(args, 30_000);
  return NextResponse.json(result);
}
