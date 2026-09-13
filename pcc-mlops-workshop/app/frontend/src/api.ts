import type {
  AppConfig,
  Kpis,
  LatencyResponse,
  PredictionSlice,
  RecentRow,
  ScoreResult,
  SpanRow,
  VolumeResponse,
} from "./types";

async function getJSON<T>(url: string): Promise<T> {
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  config: () => getJSON<AppConfig>("/api/config"),
  metrics: () => getJSON<Kpis>("/api/metrics"),
  volume: () => getJSON<VolumeResponse>("/api/volume"),
  latency: () => getJSON<LatencyResponse>("/api/latency"),
  predictions: () => getJSON<PredictionSlice[]>("/api/predictions"),
  spans: () => getJSON<SpanRow[]>("/api/spans"),
  recent: (limit = 50) => getJSON<RecentRow[]>(`/api/recent?limit=${limit}`),

  async score(patientId: number): Promise<ScoreResult> {
    const res = await fetch("/api/score", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ patient_id: patientId }),
    });
    if (!res.ok) {
      let detail = `${res.status} ${res.statusText}`;
      try {
        const body = await res.json();
        if (body?.detail) detail = body.detail;
      } catch {
        /* ignore */
      }
      throw new Error(detail);
    }
    return res.json() as Promise<ScoreResult>;
  },
};
