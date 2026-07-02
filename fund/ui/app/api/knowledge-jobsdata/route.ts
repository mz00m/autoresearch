/**
 * GET  /api/knowledge-jobsdata           — returns the markdown brief
 * POST /api/knowledge-jobsdata           — { action: "seed" } seeds theses
 */
import { NextRequest, NextResponse } from "next/server";
import { runPython } from "@/lib/run_py";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET() {
  const r = await runPython(["-m", "fund.knowledge.jobsdata", "--brief"], 30_000);
  return NextResponse.json({
    exit_code: r.exit_code,
    brief: r.stdout,
    stderr: r.stderr,
  });
}

export async function POST(req: NextRequest) {
  const { action } = (await req.json().catch(() => ({}))) as { action?: string };
  if (action !== "seed") {
    return NextResponse.json({ error: "action must be 'seed'" }, { status: 400 });
  }
  const r = await runPython(
    ["-m", "fund.knowledge.jobsdata", "--seed-theses"],
    30_000,
  );
  return NextResponse.json({
    exit_code: r.exit_code,
    stdout: r.stdout,
    stderr: r.stderr,
  });
}
