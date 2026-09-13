/** Shapes returned by the FastAPI backend (server/routes/*). */

export interface AppConfig {
  endpoint_name: string;
  warehouse_id: string;
  catalog: string;
  schema: string;
  payload_table: string;
  otel_table: string;
  patient_id_key: string;
  sample_patients: { low?: number[]; high?: number[]; [k: string]: number[] | undefined };
}

export interface Kpis {
  total_requests: number;
  error_rate_pct: number;
  p50_ms: number | null;
  p95_ms: number | null;
  p99_ms: number | null;
  distinct_patients: number;
  window_start: string | null;
  window_end: string | null;
}

export interface VolumePoint {
  bucket: string;
  requests: number;
}
export interface VolumeResponse {
  bucket_unit: string;
  series: VolumePoint[];
}

export interface LatencyPoint {
  bucket: string;
  p50_ms: number | null;
  p95_ms: number | null;
}
export interface LatencyResponse {
  bucket_unit: string;
  series: LatencyPoint[];
}

export interface PredictionSlice {
  prediction: number | null;
  label: string;
  count: number;
}

export interface SpanRow {
  span: string;
  label: string;
  requests: number;
  avg_ms: number | null;
  p50_ms: number | null;
  p95_ms: number | null;
}

export interface RecentRow {
  request_time: string;
  patient_id: number | null;
  prediction: number | null;
  risk: "HIGH" | "LOW" | null;
  latency_ms: number | null;
  status_code: number | null;
}

export interface ScoreResult {
  patient_id: number;
  prediction: number;
  risk: "HIGH" | "LOW";
  latency_ms: number;
  endpoint: string;
}
