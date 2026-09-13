import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { VolumeResponse } from "../types";
import { cssVar, fmtBucketFull, fmtBucketTick, fmtInt } from "../theme";
import { ChartCard } from "./ChartCard";
import { ChartTooltip } from "./ChartTooltip";

interface Props {
  data: VolumeResponse | null;
  loading: boolean;
  error?: string | null;
}

export function VolumeChart({ data, loading, error }: Props) {
  const blue = cssVar("--series-blue");
  const grid = cssVar("--grid");
  const axis = cssVar("--axis");
  const surface = cssVar("--surface");
  const unit = data?.bucket_unit ?? "MINUTE";
  const series = data?.series ?? [];

  return (
    <ChartCard
      title="Request volume"
      subtitle={`Requests per ${unit.toLowerCase()}`}
      loading={loading}
      error={error}
      empty={series.length === 0}
    >
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={series} margin={{ top: 8, right: 12, bottom: 0, left: 4 }}>
          <defs>
            <linearGradient id="volFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={blue} stopOpacity={0.16} />
              <stop offset="100%" stopColor={blue} stopOpacity={0.02} />
            </linearGradient>
          </defs>
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
            width={44}
            tickFormatter={(v) => fmtInt(v)}
            axisLine={false}
            tickLine={false}
            tickMargin={6}
          />
          <Tooltip
            cursor={{ stroke: axis, strokeWidth: 1 }}
            content={
              <ChartTooltip
                titleFormatter={(l) => fmtBucketFull(String(l))}
                valueFormatter={(v) => `${fmtInt(Number(v))} req`}
              />
            }
          />
          <Area
            type="monotone"
            dataKey="requests"
            name="Requests"
            stroke={blue}
            strokeWidth={2}
            fill="url(#volFill)"
            dot={false}
            activeDot={{ r: 4, stroke: surface, strokeWidth: 2 }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}
