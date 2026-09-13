import { useState } from "react";
import { api } from "../api";
import type { AppConfig, ScoreResult } from "../types";
import { fmtMs } from "../theme";
import { Card } from "./Card";
import { AlertIcon, LoaderIcon, ShieldCheckIcon } from "./icons";

interface ScorePanelProps {
  config: AppConfig | null;
}

export function ScorePanel({ config }: ScorePanelProps) {
  const [value, setValue] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ScoreResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const samples: number[] = [
    ...(config?.sample_patients?.low ?? []).slice(0, 3),
    ...(config?.sample_patients?.high ?? []).slice(0, 3),
  ];
  const uniqueSamples = Array.from(new Set(samples)).slice(0, 6);

  async function score(id: number) {
    setLoading(true);
    setError(null);
    try {
      const res = await api.score(id);
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Scoring failed");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  function submit() {
    const id = parseInt(value.trim(), 10);
    if (Number.isNaN(id)) {
      setError("Enter a numeric patient id (e.g. 100000).");
      return;
    }
    void score(id);
  }

  const endpoint = config?.endpoint_name ?? "the serving endpoint";

  return (
    <Card
      title="Score a patient"
      subtitle="Real-time 30-day readmission risk. The feature-store model looks feature values up online — you pass only the patient id."
    >
      <div className="score" style={{ marginTop: 16 }}>
        <div className="score__form">
          <div className="score__controls">
            <input
              className="input"
              inputMode="numeric"
              placeholder="Patient id, e.g. 100000"
              value={value}
              onChange={(e) => setValue(e.target.value.replace(/[^0-9]/g, ""))}
              onKeyDown={(e) => e.key === "Enter" && submit()}
              aria-label="Patient id"
            />
            <button className="btn btn--primary" onClick={submit} disabled={loading || !value}>
              {loading ? (
                <>
                  <LoaderIcon className="spin" /> Scoring…
                </>
              ) : (
                "Score patient"
              )}
            </button>
          </div>

          {uniqueSamples.length > 0 && (
            <div className="score__chips">
              <span className="score__chips-label">Try:</span>
              {uniqueSamples.map((id) => (
                <button
                  key={id}
                  className="chip"
                  onClick={() => {
                    setValue(String(id));
                    void score(id);
                  }}
                  disabled={loading}
                >
                  <span className="chip__key">{id}</span>
                </button>
              ))}
            </div>
          )}

          {error && (
            <div className="score__error">
              <AlertIcon size={14} style={{ verticalAlign: "-2px", marginRight: 6 }} />
              {error}
            </div>
          )}

          <p className="card__note">
            Endpoint <code style={{ fontSize: 12 }}>{endpoint}</code> · valid sample ids are
            integers ≈ 100000–104000.
          </p>
        </div>

        <ResultCard result={result} loading={loading} />
      </div>
    </Card>
  );
}

function ResultCard({ result, loading }: { result: ScoreResult | null; loading: boolean }) {
  if (!result) {
    return (
      <div className="result result--placeholder">
        {loading ? "Scoring…" : "Score a patient to see their predicted readmission risk."}
      </div>
    );
  }

  const high = result.risk === "HIGH";
  return (
    <div className={`result ${high ? "result--high" : "result--low"}`}>
      <div className={`result__badge ${high ? "result__badge--high" : "result__badge--low"}`}>
        <span className="result__badge-icon">
          {high ? <AlertIcon size={18} /> : <ShieldCheckIcon size={18} />}
        </span>
        {high ? "High risk" : "Low risk"}
      </div>
      <div className="result__detail">
        {high
          ? "Model predicts a 30-day readmission for this patient."
          : "Model predicts no 30-day readmission for this patient."}
      </div>
      <div className="result__grid">
        <div>
          <div className="result__metric-label">Patient</div>
          <div className="result__metric-value">{result.patient_id}</div>
        </div>
        <div>
          <div className="result__metric-label">Prediction</div>
          <div className="result__metric-value">{result.prediction}</div>
        </div>
        <div>
          <div className="result__metric-label">Round-trip</div>
          <div className="result__metric-value">{fmtMs(result.latency_ms)}</div>
        </div>
        <div>
          <div className="result__metric-label">Class</div>
          <div className="result__metric-value">{high ? "1" : "0"}</div>
        </div>
      </div>
    </div>
  );
}
