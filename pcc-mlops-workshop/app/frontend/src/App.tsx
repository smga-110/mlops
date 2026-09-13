import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type {
  AppConfig,
  Kpis,
  LatencyResponse,
  PredictionSlice,
  RecentRow,
  SpanRow,
  VolumeResponse,
} from "./types";
import { ScorePanel } from "./components/ScorePanel";
import { KpiCards } from "./components/KpiCards";
import { VolumeChart } from "./components/VolumeChart";
import { LatencyChart } from "./components/LatencyChart";
import { PredictionDonut } from "./components/PredictionDonut";
import { SpanBar } from "./components/SpanBar";
import { RecentTable } from "./components/RecentTable";
import { ActivityIcon, LoaderIcon, RefreshIcon } from "./components/icons";

export default function App() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [kpis, setKpis] = useState<Kpis | null>(null);
  const [volume, setVolume] = useState<VolumeResponse | null>(null);
  const [latency, setLatency] = useState<LatencyResponse | null>(null);
  const [predictions, setPredictions] = useState<PredictionSlice[] | null>(null);
  const [spans, setSpans] = useState<SpanRow[] | null>(null);
  const [recent, setRecent] = useState<RecentRow[] | null>(null);

  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);

  const loadDashboard = useCallback(async () => {
    setLoading(true);
    const next: Record<string, string> = {};
    async function settle<T>(key: string, p: Promise<T>, set: (v: T) => void) {
      try {
        set(await p);
      } catch (e) {
        next[key] = e instanceof Error ? e.message : String(e);
      }
    }
    await Promise.all([
      settle("metrics", api.metrics(), setKpis),
      settle("volume", api.volume(), setVolume),
      settle("latency", api.latency(), setLatency),
      settle("predictions", api.predictions(), setPredictions),
      settle("spans", api.spans(), setSpans),
      settle("recent", api.recent(50), setRecent),
    ]);
    setErrors(next);
    setUpdatedAt(new Date());
    setLoading(false);
  }, []);

  useEffect(() => {
    api.config().then(setConfig).catch(() => undefined);
    void loadDashboard();
  }, [loadDashboard]);

  const healthy = !errors.metrics && !!kpis;
  const anyError = Object.keys(errors).length > 0;
  const firstError = anyError ? Object.values(errors)[0] : null;

  return (
    <div className="app">
      <header className="header">
        <div>
          <div className="header__title-row">
            <span className="header__mark">
              <ActivityIcon size={20} />
            </span>
            <h1>PRTH Readmission — Endpoint Monitor</h1>
          </div>
          <p className="header__subtitle">
            Live monitoring and scoring for model serving endpoint{" "}
            <code>{config?.endpoint_name ?? "prth-readmission-…"}</code>
          </p>
        </div>
        <div className="header__meta">
          <span className="pill">
            <span
              className="pill__dot"
              style={{ background: healthy ? "var(--good)" : "var(--critical)" }}
            />
            {healthy ? "Connected" : loading ? "Loading" : "Connection issue"}
          </span>
          <div className="header__actions">
            {updatedAt && (
              <span className="updated">
                Updated{" "}
                {updatedAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
              </span>
            )}
            <button className="btn" onClick={() => void loadDashboard()} disabled={loading}>
              {loading ? <LoaderIcon className="spin" /> : <RefreshIcon />}
              Refresh
            </button>
          </div>
        </div>
      </header>

      <div className="stack">
        {anyError && (
          <div className="banner">
            <strong>Some dashboard data couldn’t load.</strong> {firstError}
            <div style={{ marginTop: 4, color: "var(--text-secondary)" }}>
              The app service principal may need CAN USE on the SQL warehouse and SELECT on the
              tracking tables.
            </div>
          </div>
        )}

        <ScorePanel config={config} />

        <KpiCards kpis={kpis} loading={loading} />

        <div>
          <div className="section-label">Endpoint performance</div>
          <div className="charts">
            <VolumeChart data={volume} loading={loading} error={errors.volume} />
            <LatencyChart data={latency} loading={loading} error={errors.latency} />
            <PredictionDonut data={predictions} loading={loading} error={errors.predictions} />
            <SpanBar data={spans} loading={loading} error={errors.spans} />
          </div>
        </div>

        <RecentTable rows={recent} loading={loading} error={errors.recent} />
      </div>

      <footer className="footer">
        {config && (
          <>
            <span>
              Warehouse <code>{config.warehouse_id}</code>
            </span>
            <span>
              Payload <code>{config.payload_table}</code>
            </span>
            <span>
              Spans <code>{config.otel_table}</code>
            </span>
          </>
        )}
      </footer>
    </div>
  );
}
