"""Score-a-patient endpoint: wraps the model serving endpoint."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..databricks_client import score_patient

router = APIRouter(tags=["score"])


class ScoreRequest(BaseModel):
    patient_id: int = Field(..., description="Patient key for the online feature lookup")


class ScoreResponse(BaseModel):
    patient_id: int
    prediction: int
    risk: str
    latency_ms: float
    endpoint: str


@router.post("/score", response_model=ScoreResponse)
def score(req: ScoreRequest) -> ScoreResponse:
    try:
        result = score_patient(req.patient_id)
    except Exception as exc:  # surface a clean error to the UI
        raise HTTPException(status_code=502, detail=f"Scoring failed: {exc}") from exc
    return ScoreResponse(**result)
