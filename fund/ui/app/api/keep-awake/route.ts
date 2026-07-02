/**
 * POST /api/keep-awake — start | stop | status the caffeinate wrapper.
 * Body: { action: "start"|"stop"|"status", hours?: number }
 */
import { NextRequest, NextResponse } from "next/server";
import { runPython } from "@/lib/run_py";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(req: NextRequest) {
  const { action, hours = 24 } = (await req.json().catch(() => ({}))) as {
    action?: "start" | "stop" | "status";
    hours?: number;
  };
  if (!["start", "stop", "status"].includes(action ?? "")) {
    return NextResponse.json({ error: "action must be start|stop|status" }, { status: 400 });
  }
  const args = ["-m", "fund.keep_awake", `--${action}`];
  if (action === "start") args.push("--hours", String(hours));
  const r = await runPython(args, 15_000);
  let parsed: unknown = null;
  try {
    parsed = JSON.parse(r.stdout || "{}");
  } catch {
    parsed = { error: "could not parse output", raw: r.stdout };
  }
  return NextResponse.json({
    exit_code: r.exit_code, stderr: r.stderr, result: parsed,
  });
}

export async function GET() {
  const r = await runPython(["-m", "fund.keep_awake", "--status"], 10_000);
  let parsed: unknown = null;
  try { parsed = JSON.parse(r.stdout || "{}"); } catch { parsed = {}; }
  return NextResponse.json({ result: parsed });
}
