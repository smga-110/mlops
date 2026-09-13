import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { LatencyResponse } from "../types";
import { cssVar, fmtBucketFull, fmtBucketTick, fmtMs } from "../theme";
import { ChartCard } from "./ChartCard";
import { ChartTooltip } from "./ChartTooltip";

interface Props {
  data: LatencyResponse | null;
  loading: boolean;
  error?: string | null;
}

export function LatencyChart({ data, loading, error }: Props) {
  const blue = cssVar("--series-blue");
  const orange = cssVar("--series-orange");
  const grid = cssVar("--grid");
  const axis = cssVar("--axis");
  const surface = cssVar("--surface");
  const unit = data?.bucket_unit ?? "MINUTE";
  const series = data?.series ?? [];

  return (
    <ChartCard
      title="Latency over time"
      subtitle="Endpoint execution duration (p50 / p95)"
      loading={loading}
      error={error}
      empty={series.length === 0}
    >
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={series} margin={{ top: 8, right: 14, bottom: 0, left: 4 }}>
          <CartesianGrid vertical={false} stroke={grid} />
          <XAxis
            dataKey="bucket"
            tickFormatter={(v) => fmtBucketTick(v, unit)}
            axisLine={{ stroke: axis }}
            tickLine={false}
            minTickGap={44}
            tickMargin={8}
          />
          <YAxis
            width={48}
            tickFormatter={(v) => `${v} ms`}
            axisLine={false}
            tickLine={false}
            tickMargin={6}
          />
          <Tooltip
            cursor={{ stroke: axis, strokeWidth: 1 }}
            content={
              <ChartTooltip
                titleFormatter={(l) => fmtBucketFull(String(l))}
                valueFormatter={(v) => fmtMs(Number(v))}
              />
            }
          />
          <Legend
            iconType="plainline"
            wrapperStyle={{ paddingTop: 6 }}
            formatter={(v) => <span style={{ color: "var(--text-secondary)" }}>{v}</span>}
          />
          <Line
            type="monotone"
            dataKey="p50_ms"
            name="p50"
            stroke={blue}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, stroke: surface, strokeWidth: 2 }}
          />
          <Line
            type="monotone"
            dataKey="p95_ms"
            name="p95"
            stroke={orange}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, stroke: surface, strokeWidth: 2 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}
