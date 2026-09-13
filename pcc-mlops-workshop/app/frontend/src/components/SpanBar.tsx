import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ReactNode } from "react";
import type { SpanRow } from "../types";
import { cssVar, fmtMs } from "../theme";
import { ChartCard } from "./ChartCard";
import { ChartTooltip } from "./ChartTooltip";

interface Props {
  data: SpanRow[] | null;
  loading: boolean;
  error?: string | null;
}

export function SpanBar({ data, loading, error }: Props) {
  const blue = cssVar("--series-blue");
  const orange = cssVar("--series-orange");
  const grid = cssVar("--grid");
  const axis = cssVar("--axis");
  const ink = cssVar("--text-secondary");
  const rows = data ?? [];

  // rows arrive sorted by avg_ms DESC → rows[0] is the dominant span.
  let headline: ReactNode = undefined;
  if (rows.length >= 2 && rows[0].p95_ms != null && rows[1].p95_ms != null) {
    headline = (
      <>
        <strong>{rows[0].label}</strong> dominates end-to-end latency — p95 {fmtMs(rows[0].p95_ms)} vs{" "}
        {fmtMs(rows[1].p95_ms)} for {rows[1].label.toLowerCase()}.
      </>
    );
  }

  return (
    <ChartCard
      title="Latency by span"
      subtitle="Where the time goes inside each request (p50 / p95)"
      loading={loading}
      error={error}
      empty={rows.length === 0}
      tall
      headline={headline}
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          layout="vertical"
          data={rows}
          margin={{ top: 4, right: 56, bottom: 0, left: 8 }}
          barGap={2}
          barCategoryGap="30%"
        >
          <CartesianGrid horizontal={false} stroke={grid} />
          <XAxis
            type="number"
            tickFormatter={(v) => `${v} ms`}
            axisLine={{ stroke: axis }}
            tickLine={false}
            domain={[0, (dataMax: number) => Math.ceil((dataMax + 6) / 5) * 5]}
            tickMargin={6}
          />
          <YAxis
            type="category"
            dataKey="label"
            width={112}
            axisLine={false}
            tickLine={false}
            tickMargin={6}
          />
          <Tooltip
            cursor={{ fill: "color-mix(in srgb, var(--series-blue) 6%, transparent)" }}
            content={
              <ChartTooltip
                titleFormatter={(_, row) => String(row?.label ?? "")}
                valueFormatter={(v) => fmtMs(Number(v))}
              />
            }
          />
          <Legend
            wrapperStyle={{ paddingTop: 8 }}
            formatter={(v) => <span style={{ color: "var(--text-secondary)" }}>{v}</span>}
          />
          <Bar dataKey="p50_ms" name="p50" fill={blue} barSize={15} radius={[0, 4, 4, 0]}>
            {rows.map((r) => (
              <Cell key={`p50-${r.span}`} />
            ))}
            <LabelList
              dataKey="p50_ms"
              position="right"
              formatter={(v: number) => fmtMs(v)}
              style={{ fill: ink, fontSize: 11, fontVariantNumeric: "tabular-nums" }}
            />
          </Bar>
          <Bar dataKey="p95_ms" name="p95" fill={orange} barSize={15} radius={[0, 4, 4, 0]}>
            {rows.map((r) => (
              <Cell key={`p95-${r.span}`} />
            ))}
            <LabelList
              dataKey="p95_ms"
              position="right"
              formatter={(v: number) => fmtMs(v)}
              style={{ fill: ink, fontSize: 11, fontVariantNumeric: "tabular-nums" }}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}
