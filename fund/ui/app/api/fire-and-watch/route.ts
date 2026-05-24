/**
 * POST /api/fire-and-watch
 * Body: { broker: "alpaca"|"ibkr", waitSeconds?: number (default 60) }
 *
 * Atomic flow: send_orders → wait → reconcile. Returns the merged stdout +
 * exit codes for both phases. Single round-trip from the user's perspective.
 *
 * For paper accounts where fills typically settle within seconds, the default
 * 60s wait is comfortable. For thinly-traded names, bump waitSeconds.
 */
import { NextRequest, NextResponse } from "next/server";
import { runPython } from "@/lib/run_py";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => ({}))) as {
    broker?: "alpaca" | "ibkr";
    waitSeconds?: number;
  };
  if (body.broker !== "alpaca" && body.broker !== "ibkr") {
    return NextResponse.json({ error: "broker must be alpaca|ibkr" }, { status: 400 });
  }
  const wait = Math.min(300, Math.max(10, body.waitSeconds ?? 60));

  const sent = await runPython(
    ["-m", "fund.send_orders", "--broker", body.broker, "--yes"],
    120_000,
  );
  if (sent.exit_code !== 0) {
    return NextResponse.json({
      phase: "send_failed",
      sent,
      reconciled: null,
      wait_seconds: 0,
    });
  }

  // Sleep server-side so the client just sees one in-flight request.
  await new Promise((r) => setTimeout(r, wait * 1000));

  const reconciled = await runPython(
    ["-m", "fund.reconcile", "--broker", body.broker],
    120_000,
  );
  return NextResponse.json({
    phase: "completed",
    sent, reconciled, wait_seconds: wait,
  });
}
