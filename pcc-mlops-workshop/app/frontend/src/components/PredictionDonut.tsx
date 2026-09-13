import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import type { PredictionSlice } from "../types";
import { cssVar, fmtInt } from "../theme";
import { Card } from "./Card";
import { ChartTooltip } from "./ChartTooltip";
import { AlertIcon } from "./icons";

interface Props {
  data: PredictionSlice[] | null;
  loading: boolean;
  error?: string | null;
}

function colorFor(prediction: number | null): string {
  if (prediction === 1) return cssVar("--series-red");
  if (prediction === 0) return cssVar("--series-blue");
  return cssVar("--text-muted");
}

export function PredictionDonut({ data, loading, error }: Props) {
  const surface = cssVar("--surface");
  const slices = (data ?? []).filter((s) => (s.count ?? 0) > 0);
  const total = slices.reduce((acc, s) => acc + (s.count ?? 0), 0);

  const body = () => {
    if (loading) {
      return (
        <div className="chart-body">
          <div className="skeleton" style={{ width: "100%", height: "100%" }} />
        </div>
      );
    }
    if (error) {
      return (
        <div className="chart-error">
          <AlertIcon size={20} style={{ color: "var(--text-muted)" }} />
          <div>Couldn’t load this chart.</div>
          <div style={{ fontSize: 12 }}>{error}</div>
        </div>
      );
    }
    if (slices.length === 0) return <div className="chart-error">No predictions in range.</div>;

    return (
      <>
        <div className="donut-wrap" style={{ height: 210, marginTop: 8 }}>
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={slices}
                dataKey="count"
                nameKey="label"
                innerRadius="62%"
                outerRadius="88%"
                paddingAngle={2}
                stroke={surface}
                strokeWidth={2}
                startAngle={90}
                endAngle={-270}
                isAnimationActive={false}
              >
                {slices.map((s) => (
                  <Cell key={s.label} fill={colorFor(s.prediction)} />
                ))}
              </Pie>
              <Tooltip
                content={
                  <ChartTooltip
                    valueFormatter={(v) =>
                      `${fmtInt(Number(v))} (${total ? ((Number(v) / total) * 100).toFixed(1) : "0"}%)`
                    }
                  />
                }
              />
            </PieChart>
          </ResponsiveContainer>
          <div className="donut-center">
            <div className="donut-center__value">{fmtInt(total)}</div>
            <div className="donut-center__label">scored</div>
          </div>
        </div>

        <div className="donut-legend" style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 12 }}>
          {slices.map((s) => {
            const pct = total ? ((s.count / total) * 100).toFixed(1) : "0";
            return (
              <div
                key={s.label}
                style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}
              >
                <span style={{ display: "inline-flex", alignItems: "center", gap: 8, color: "var(--text-secondary)" }}>
                  <span
                    className="tooltip__swatch"
                    style={{ background: colorFor(s.prediction), width: 10, height: 10 }}
                  />
                  {s.label}
                </span>
                <span style={{ color: "var(--text-primary)", fontVariantNumeric: "tabular-nums" }}>
                  <strong style={{ fontWeight: 650 }}>{fmtInt(s.count)}</strong>
                  <span style={{ color: "var(--text-muted)", marginLeft: 6 }}>{pct}%</span>
                </span>
              </div>
            );
          })}
        </div>
      </>
    );
  };

  return (
    <Card title="Prediction mix" subtitle="Predicted 30-day readmission outcomes">
      {body()}
    </Card>
  );
}
