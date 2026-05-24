/**
 * GET /api/schedule-status — list of scheduled jobs + last-run state.
 * POST /api/schedule-status — { action: "install"|"uninstall"|"once" }
 */
import { NextRequest, NextResponse } from "next/server";
import { promises as fs } from "fs";
import path from "path";
import os from "os";
import { runPython } from "@/lib/run_py";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const STATE_PATH = path.join(os.homedir(), ".fund", "scheduler_state.json");
const LOG_PATH = path.join(os.homedir(), ".fund", "scheduler.log");

const JOBS = [
  { name: "refresh_pre_open", time: "05:30", description: "Refresh dashboard cards before market open" },
  { name: "morning", time: "08:00", description: "Generate today's pending tickets" },
  { name: "place_stops", time: "10:30", description: "Trailing stops on new broker positions" },
  { name: "sync_from_broker", time: "10:35", description: "Pull broker fills + cash back to local state" },
  { name: "closeout", time: "16:15", description: "Close out the day (mark-to-market, log row)" },
  { name: "refresh_post_close", time: "16:30", description: "Refresh dashboard cards after market close" },
];

export async function GET() {
  let state: Record<string, Record<string, string>> = {};
  try {
    state = JSON.parse(await fs.readFile(STATE_PATH, "utf8"));
  } catch {}
  let logTail: string[] = [];
  try {
    const log = await fs.readFile(LOG_PATH, "utf8");
    logTail = log.trim().split("\n").slice(-40);
  } catch {}
  let installed = false;
  try {
    await fs.stat(path.join(os.homedir(), "Library/LaunchAgents/com.fund.scheduler.plist"));
    installed = true;
  } catch {}
  return NextResponse.json({
    jobs: JOBS.map((j) => ({
      ...j,
      last_success: state.last_success?.[j.name] ?? null,
      last_run: state.last_run?.[j.name] ?? null,
      last_exit: state.last_exit?.[j.name] ?? null,
    })),
    installed,
    log_tail: logTail,
  });
}

export async function POST(req: NextRequest) {
  const { action } = (await req.json().catch(() => ({}))) as { action?: string };
  if (!["install", "uninstall", "once"].includes(action ?? "")) {
    return NextResponse.json(
      { error: "action must be install | uninstall | once" },
      { status: 400 }
    );
  }
  const args = ["-m", "fund.scheduler", `--${action}`];
  const result = await runPython(args, 30_000);
  return NextResponse.json(result);
}
