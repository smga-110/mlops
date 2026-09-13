/** Shared Recharts tooltip: a titled card with coloured series rows. */
interface TooltipEntry {
  name?: string | number;
  value?: number | string;
  color?: string;
  dataKey?: string | number;
  payload?: Record<string, unknown>;
}

interface ChartTooltipProps {
  active?: boolean;
  payload?: TooltipEntry[];
  label?: string | number;
  titleFormatter?: (label: string | number | undefined, row?: Record<string, unknown>) => string;
  valueFormatter?: (value: number | string | undefined, entry: TooltipEntry) => string;
}

export function ChartTooltip({
  active,
  payload,
  label,
  titleFormatter,
  valueFormatter,
}: ChartTooltipProps) {
  if (!active || !payload || payload.length === 0) return null;
  const title = titleFormatter ? titleFormatter(label, payload[0]?.payload) : String(label ?? "");
  return (
    <div className="tooltip">
      {title && <div className="tooltip__title">{title}</div>}
      {payload.map((entry, i) => (
        <div className="tooltip__row" key={i}>
          <span className="tooltip__key">
            <span className="tooltip__swatch" style={{ background: entry.color }} />
            {entry.name}
          </span>
          <span className="tooltip__val">
            {valueFormatter ? valueFormatter(entry.value, entry) : String(entry.value)}
          </span>
        </div>
      ))}
    </div>
  );
}
