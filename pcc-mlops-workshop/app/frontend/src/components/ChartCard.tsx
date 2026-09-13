import type { ReactNode } from "react";
import { Card } from "./Card";
import { AlertIcon } from "./icons";

interface ChartCardProps {
  title: string;
  subtitle?: string;
  loading: boolean;
  error?: string | null;
  empty?: boolean;
  tall?: boolean;
  headline?: ReactNode;
  children: ReactNode;
}

/** Card wrapper for a chart, with consistent loading / error / empty states. */
export function ChartCard({
  title,
  subtitle,
  loading,
  error,
  empty,
  tall,
  headline,
  children,
}: ChartCardProps) {
  const bodyClass = `chart-body${tall ? " chart-body--tall" : ""}`;
  return (
    <Card title={title} subtitle={subtitle}>
      {loading ? (
        <div className={bodyClass}>
          <div className="skeleton" style={{ width: "100%", height: "100%" }} />
        </div>
      ) : error ? (
        <div className="chart-error">
          <AlertIcon size={20} style={{ color: "var(--text-muted)" }} />
          <div>Couldn’t load this chart.</div>
          <div style={{ fontSize: 12 }}>{error}</div>
        </div>
      ) : empty ? (
        <div className="chart-error">No data in range.</div>
      ) : (
        <>
          <div className={bodyClass}>{children}</div>
          {headline && <p className="headline">{headline}</p>}
        </>
      )}
    </Card>
  );
}
