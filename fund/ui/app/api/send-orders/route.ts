/**
 * POST /api/send-orders
 * Body: { broker: "alpaca" | "ibkr", dryRun?: boolean }
 *
 * Shells to `python3 -m fund.send_orders --broker $broker [--yes | --dry-run]`
 * and streams stdout back as a single response. Localhost-only by design;
 * the dashboard is a single-user laptop tool.
 */
import { NextRequest, NextResponse } from "next/server";
import { spawn } from "child_process";
import path from "path";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const FUND_ROOT = path.resolve(process.cwd(), "..");
const REPO_ROOT = path.resolve(FUND_ROOT, "..");

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

  const args = ["-m", "fund.send_orders", "--broker", broker];
  if (dryRun) args.push("--dry-run");
  else args.push("--yes"); // skip per-ticket confirmation; UI gate is the user click

  return new Promise<Response>((resolve) => {
    const child = spawn("python3", args, {
      cwd: REPO_ROOT,
      env: { ...process.env },
    });

    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk: Buffer) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk: Buffer) => {
      stderr += chunk.toString();
    });
    child.on("close", (code: number | null) => {
      resolve(
        NextResponse.json({
          exit_code: code ?? -1,
          stdout,
          stderr,
          dry_run: !!dryRun,
          broker,
        })
      );
    });
    child.on("error", (err: Error) => {
      resolve(
        NextResponse.json(
          {
            error: `failed to spawn python3: ${err.message}. ` +
              `Is python3 on PATH and the fund package installed?`,
          },
          { status: 500 }
        )
      );
    });
  });
}
