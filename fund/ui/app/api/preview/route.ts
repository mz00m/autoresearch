/**
 * POST /api/preview  — single-strategy recommendation, no state change.
 * Body: { strategy: string, params?: object, asOf?: string }
 * Returns the JSON output of fund.preview (allocation + weights + prices).
 */
import { NextRequest, NextResponse } from "next/server";
import { runPython } from "@/lib/run_py";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => ({}))) as {
    strategy?: string;
    params?: Record<string, unknown>;
    asOf?: string;
    source?: string;
  };
  if (!body.strategy) {
    return NextResponse.json({ error: "strategy required" }, { status: 400 });
  }
  const args = [
    "-m", "fund.preview",
    "--strategy", body.strategy,
    "--params", JSON.stringify(body.params ?? {}),
    "--source", body.source ?? "auto",
  ];
  if (body.asOf) args.push("--as-of", body.asOf);
  const result = await runPython(args, 120_000);
  // fund.preview writes JSON to stdout — parse it for the client
  let parsed: unknown = null;
  try {
    parsed = JSON.parse(result.stdout || "{}");
  } catch {
    parsed = { error: "could not parse preview output", raw: result.stdout };
  }
  return NextResponse.json({
    exit_code: result.exit_code,
    stderr: result.stderr,
    command: result.command,
    preview: parsed,
  });
}
