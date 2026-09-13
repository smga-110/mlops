import type { RecentRow } from "../types";
import { fmtBucketFull, fmtInt, fmtMs } from "../theme";
import { Card } from "./Card";
import { AlertIcon } from "./icons";

interface Props {
  rows: RecentRow[] | null;
  loading: boolean;
  error?: string | null;
}

export function RecentTable({ rows, loading, error }: Props) {
  return (
    <Card title="Recent requests" subtitle="Most recent scoring calls logged to the inference table">
      {loading ? (
        <div className="table-wrap" style={{ padding: 8 }}>
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="skeleton" style={{ height: 20, margin: 8 }} />
          ))}
        </div>
      ) : error ? (
        <div className="chart-error" style={{ height: 160 }}>
          <AlertIcon size={20} style={{ color: "var(--text-muted)" }} />
          <div>Couldn’t load recent requests.</div>
          <div style={{ fontSize: 12 }}>{error}</div>
        </div>
      ) : !rows || rows.length === 0 ? (
        <div className="chart-error" style={{ height: 160 }}>No recent requests.</div>
      ) : (
        <div className="table-wrap">
          <table className="recent">
            <thead>
              <tr>
                <th>Time</th>
                <th>Patient</th>
                <th>Prediction</th>
                <th>Risk</th>
                <th>Latency</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td className="td-mono">{fmtBucketFull(r.request_time)}</td>
                  <td className="td-num">{r.patient_id ?? "—"}</td>
                  <td className="td-num">{r.prediction ?? "—"}</td>
                  <td>
                    {r.risk === "HIGH" ? (
                      <span className="tag tag--high">
                        <span className="tag__dot" /> High
                      </span>
                    ) : r.risk === "LOW" ? (
                      <span className="tag tag--low">
                        <span className="tag__dot" /> Low
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="td-num">{fmtMs(r.latency_ms)}</td>
                  <td>
                    <span className={r.status_code === 200 ? "status-ok" : "td-num"}>
                      {r.status_code ?? "—"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {rows && rows.length > 0 && (
        <p className="card__note" style={{ marginTop: 10 }}>
          Showing {fmtInt(rows.length)} most recent requests.
        </p>
      )}
    </Card>
  );
}
