/**
 * GET  /api/thesis            — list all theses (active + invalidated)
 * POST /api/thesis            — { symbol, catalyst, killSwitch, horizon, confidence }
 *                               add a new thesis
 * POST /api/thesis (invalidate) — { symbol, reason, action: "invalidate" }
 */
import { NextRequest, NextResponse } from "next/server";
import { promises as fs } from "fs";
import path from "path";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const FUND_ROOT = path.resolve(process.cwd(), "..");
const THESES_PATH = path.join(FUND_ROOT, "theses.json");

type ThesisRow = {
  symbol: string;
  catalyst: string;
  kill_switch: string;
  horizon: string;
  confidence: number;
  created_at: string;
  author: string;
  status: "active" | "invalidated" | "expired";
  invalidated_at?: string;
  invalidated_reason?: string;
};

async function readAll(): Promise<ThesisRow[]> {
  try {
    const raw = await fs.readFile(THESES_PATH, "utf8");
    return JSON.parse(raw) as ThesisRow[];
  } catch (e: unknown) {
    if ((e as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw e;
  }
}

async function writeAll(rows: ThesisRow[]): Promise<void> {
  await fs.writeFile(THESES_PATH, JSON.stringify(rows, null, 2));
}

export async function GET() {
  return NextResponse.json({ theses: await readAll() });
}

export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => ({}))) as Record<string, unknown>;
  const rows = await readAll();

  if (body.action === "invalidate") {
    const symbol = String(body.symbol || "").toUpperCase();
    const reason = String(body.reason || "");
    if (!symbol || !reason) {
      return NextResponse.json({ error: "symbol + reason required" }, { status: 400 });
    }
    let touched = 0;
    for (const r of rows) {
      if (r.symbol.toUpperCase() === symbol && r.status === "active") {
        r.status = "invalidated";
        r.invalidated_at = new Date().toISOString().slice(0, 10);
        r.invalidated_reason = reason;
        touched++;
      }
    }
    if (touched > 0) await writeAll(rows);
    return NextResponse.json({ invalidated: touched });
  }

  // Add new thesis
  const symbol = String(body.symbol || "").toUpperCase();
  const catalyst = String(body.catalyst || "").trim();
  const killSwitch = String(body.killSwitch || "").trim();
  const horizon = String(body.horizon || "").trim();
  const confidence = parseInt(String(body.confidence || "0"), 10);
  if (!symbol || !catalyst || !killSwitch || !horizon) {
    return NextResponse.json(
      { error: "symbol, catalyst, killSwitch, horizon all required" },
      { status: 400 }
    );
  }
  if (!(confidence >= 1 && confidence <= 5)) {
    return NextResponse.json({ error: "confidence 1-5" }, { status: 400 });
  }
  const row: ThesisRow = {
    symbol, catalyst, kill_switch: killSwitch, horizon, confidence,
    created_at: new Date().toISOString().replace(/\.\d{3}Z$/, ""),
    author: String(body.author || "matt"),
    status: "active",
  };
  rows.push(row);
  await writeAll(rows);
  return NextResponse.json({ added: row });
}
