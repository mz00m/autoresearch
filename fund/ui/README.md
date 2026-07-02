# fund/ui — daily research dashboard

A local Next.js dashboard that reads your paper-portfolio state and renders
today's recommendations, holdings, track record, and the verdict for whether
to keep going or iterate.

This is a viewer. It never writes to `portfolio_state.json` or
`daily_log.tsv` — Python owns those. Run the morning + closeout from the
terminal; the UI just shows you the current picture.

## Run it

```bash
# one-time install
cd fund/ui
npm install

# every time
npm run dev    # http://localhost:3030
```

## Pages

| Path | What it shows |
| --- | --- |
| `/` | Today's recommendations (action), holdings, verdict, equity vs SPY |
| `/history` | Daily log table, equity curve, cumulative excess vs benchmark |
| `/compare` | The 7-strategy side-by-side (run `python3 -m fund.compare` for fresh numbers) |
| `/strategies` | Bench library with the active strategy highlighted |

## How it reads data

`lib/data.ts` reads the two state files at the parent `fund/` directory:

- `../portfolio_state.json` — cash, positions, pending tickets, filled history, active strategy
- `../daily_log.tsv` — one row per closeout (date, day return, cum return, SPY benchmark, drawdown, fills)

All reads happen in server components — no API routes needed, no client-side
data fetching.

## What it does NOT do

- **No execution.** This is a viewer. Tickets get sent to a broker via
  `fund/brokers/` (separate adapter); the UI just shows them.
- **No edits.** Switching the active strategy still requires editing
  `portfolio_state.json` (or running `fund.portfolio init --force`).
  A switching UI is on the roadmap once there's a CLI to back it.
- **No auth.** Local-only. Don't expose port 3030 to the internet.

## Stack

- Next.js 15 (App Router) + React 19
- Tailwind 3.4
- Recharts (for the equity/drawdown charts)
- Source Serif 4 for headings, system sans for body, tabular numerics throughout

Pure read-on-demand server components. No client-side state to speak of.
