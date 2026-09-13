import type { Kpis } from "../types";
import { fmtInt, fmtMs, fmtPct } from "../theme";

interface KpiCardsProps {
  kpis: Kpis | null;
  loading: boolean;
}

interface Tile {
  label: string;
  value: string;
  unit?: string;
  good?: boolean;
  sub?: string;
}

export function KpiCards({ kpis, loading }: KpiCardsProps) {
  if (loading || !kpis) {
    return (
      <div className="kpis">
        {Array.from({ length: 6 }).map((_, i) => (
          <div className="kpi" key={i}>
            <div className="skeleton" style={{ height: 12, width: "60%" }} />
            <div className="skeleton" style={{ height: 26, width: "45%", marginTop: 4 }} />
          </div>
        ))}
      </div>
    );
  }

  const noErrors = kpis.error_rate_pct === 0;
  const tiles: Tile[] = [
    { label: "Total requests", value: fmtInt(kpis.total_requests) },
    {
      label: "Error rate",
      value: fmtPct(kpis.error_rate_pct),
      good: noErrors,
      sub: noErrors ? "all 200 OK" : undefined,
    },
    { label: "p50 latency", value: fmtMs(kpis.p50_ms) },
    { label: "p95 latency", value: fmtMs(kpis.p95_ms) },
    { label: "p99 latency", value: fmtMs(kpis.p99_ms) },
    { label: "Distinct patients", value: fmtInt(kpis.distinct_patients) },
  ];

  return (
    <div className="kpis">
      {tiles.map((t) => (
        <div className="kpi" key={t.label}>
          <span className="kpi__label">{t.label}</span>
          <span className={`kpi__value${t.good ? " kpi__value--good" : ""}`}>{t.value}</span>
          {t.sub && <span className="kpi__sub">{t.sub}</span>}
        </div>
      ))}
    </div>
  );
}
