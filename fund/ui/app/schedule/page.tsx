import { ScheduleControls } from "@/components/ScheduleControls";

export const dynamic = "force-dynamic";

export default async function SchedulePage() {
  return (
    <div className="space-y-10">
      <header>
        <div className="eyebrow">Automation</div>
        <h1 className="font-serif text-4xl font-semibold tracking-tight mt-2">
          Scheduled jobs
        </h1>
        <p className="text-sm text-muted mt-2 max-w-2xl">
          What the system runs without a human. All times in Eastern Time (NYSE).
          The two human-gated actions — <strong>Send orders</strong> and
          <strong> Cancel orders</strong> — are deliberately NOT automated;
          they stay manual per <code className="font-mono">fund.md §7</code>.
        </p>
      </header>

      <ScheduleControls />
    </div>
  );
}
