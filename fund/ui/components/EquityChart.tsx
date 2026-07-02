"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  ReferenceLine,
} from "recharts";

type Row = { date: string; portfolio: number; benchmark?: number | null };

export function EquityChart({ rows }: { rows: Row[] }) {
  if (rows.length < 2) {
    return (
      <div className="card px-6 py-12 text-center text-muted italic text-sm">
        No track record yet — run a few days of the loop to populate this chart.
      </div>
    );
  }
  return (
    <div className="card px-2 py-4">
      <ResponsiveContainer width="100%" height={320}>
        <LineChart data={rows} margin={{ top: 12, right: 60, left: 8, bottom: 8 }}>
          <CartesianGrid stroke="#ebe7dc" strokeDasharray="2 3" vertical={false} />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 11, fill: "#6b6f76" }}
            tickFormatter={(v: string) => v.slice(5)}
            stroke="#cfccc2"
            minTickGap={32}
          />
          <YAxis
            tick={{ fontSize: 11, fill: "#6b6f76" }}
            tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
            stroke="#cfccc2"
            width={48}
          />
          <Tooltip
            contentStyle={{
              background: "#fff",
              border: "1px solid #e6e3da",
              borderRadius: 6,
              fontSize: 12,
              fontVariantNumeric: "tabular-nums",
            }}
            formatter={(v: unknown) =>
              typeof v === "number" ? `${(v * 100).toFixed(2)}%` : "—"
            }
            labelStyle={{ color: "#6b6f76", fontWeight: 500 }}
          />
          <ReferenceLine y={0} stroke="#6b6f76" strokeDasharray="2 3" />
          <Line
            type="monotone"
            dataKey="portfolio"
            stroke="#1c4f8e"
            strokeWidth={1.8}
            dot={false}
            name="Portfolio"
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="benchmark"
            stroke="#6b6f76"
            strokeWidth={1.4}
            strokeDasharray="3 3"
            dot={false}
            name="SPY"
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
