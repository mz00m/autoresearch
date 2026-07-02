import type { CoachReport } from "@/lib/data";

const TONE = {
  informational: {
    bg: "bg-paper",
    border: "border-l-accent",
    chip: "bg-accent/10 text-accent",
    label: "Informational",
  },
  watch: {
    bg: "bg-[#fbf5e6]",
    border: "border-l-watch",
    chip: "bg-watch/15 text-watch",
    label: "Watch",
  },
  action: {
    bg: "bg-[#fdf0e6]",
    border: "border-l-[#b8651a]",
    chip: "bg-[#b8651a]/15 text-[#8a4612]",
    label: "Action recommended",
  },
  urgent: {
    bg: "bg-[#fdefef]",
    border: "border-l-alert",
    chip: "bg-alert/15 text-alert",
    label: "Urgent",
  },
} as const;

export function CoachCard({ coach }: { coach: CoachReport }) {
  const tone = TONE[coach.severity];
  return (
    <article className={`card border-l-4 ${tone.border} ${tone.bg} px-6 py-5`}>
      <div className="flex items-baseline gap-3">
        <span
          className={`tag ${tone.chip} font-sans text-[10px] uppercase tracking-eyebrow px-2 py-0.5 rounded font-semibold`}
        >
          {tone.label}
        </span>
        <h2 className="font-serif text-xl font-semibold">
          {coach.headline}
        </h2>
      </div>
      <p className="text-sm text-ink/80 mt-3">{coach.rationale}</p>
      <p className="text-sm font-medium mt-3 pt-3 border-t border-rule/60">
        → {coach.next_action}
      </p>
    </article>
  );
}
