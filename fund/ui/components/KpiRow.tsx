type Kpi = {
  label: string;
  value: string;
  tone?: "default" | "pos" | "neg" | "muted";
};

export function KpiRow({ kpis }: { kpis: Kpi[] }) {
  return (
    <div className="card divide-x divide-rule grid grid-cols-2 md:grid-cols-5 overflow-hidden">
      {kpis.map((k, i) => (
        <div key={i} className="px-5 py-4">
          <div className="kpi-label">{k.label}</div>
          <div
            className={`kpi-value mt-0.5 ${
              k.tone === "pos"
                ? "text-ok"
                : k.tone === "neg"
                ? "text-alert"
                : k.tone === "muted"
                ? "text-muted"
                : ""
            }`}
          >
            {k.value}
          </div>
        </div>
      ))}
    </div>
  );
}
