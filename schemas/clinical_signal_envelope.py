"""CTIB Pydantic Schemas — Clinical Signal Envelope.

The universal output format for all MCP constraint servers.
Every MCP tool returns a ClinicalSignalEnvelope containing:
- An assertion with clinical dimension and confidence
- Evidence sources referencing FHIR resources
- AI augmentation delta explaining what AI uniquely detected
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ClinicalDimension(str, Enum):
    DETERIORATION_RISK = "deterioration_risk"
    MEDICATION_SAFETY = "medication_safety"
    CARE_GAP = "care_gap"
    TRAJECTORY_DIVERGENCE = "trajectory_divergence"
    CROSS_SIGNAL_CONFLICT = "cross_signal_conflict"


class SignalDirection(str, Enum):
    ELEVATED = "elevated"
    STABLE = "stable"
    DECLINING = "declining"
    UNKNOWN = "unknown"


class ClinicalAssertion(BaseModel):
    """A single clinical assertion derived from analysis."""
    text: str = Field(..., description="Human-readable assertion text")
    clinical_dimension: ClinicalDimension
    direction: SignalDirection
    magnitude: float = Field(..., ge=0.0, le=1.0, description="Signal strength 0-1")


class ConfidenceInterval(BaseModel):
    """Confidence interval with calibration basis."""
    lower: float = Field(..., ge=0.0, le=1.0)
    upper: float = Field(..., ge=0.0, le=1.0)
    basis: str = Field(..., description="Methodology basis for confidence")
    calibration_anchor: str = Field(..., description="Reference standard used")


class EvidenceSource(BaseModel):
    """Reference to a FHIR resource that supports the assertion."""
    fhir_resource_type: str
    fhir_resource_id: str
    loinc_code: Optional[str] = None
    snomed_code: Optional[str] = None
    description: str


class ClinicalSignalEnvelope(BaseModel):
    """Universal output format for all MCP constraint servers.

    This is the atomic unit of clinical intelligence in CTIB.
    Every MCP tool produces one or more of these envelopes.
    """
    envelope_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_mcp: str = Field(..., description="MCP server name and version")
    tool_called: str = Field(..., description="Name of the MCP tool that produced this")
    timestamp_utc: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    patient_context_token: str = Field(
        ..., description="SHARP escrow reference — NOT patient ID"
    )
    assertion: ClinicalAssertion
    confidence_interval: ConfidenceInterval
    evidence_sources: list[EvidenceSource] = Field(default_factory=list)
    conflicting_signals: list[str] = Field(
        default_factory=list,
        description="IDs of envelopes that conflict with this one"
    )
    open_question_generated: Optional[str] = Field(
        None, description="FHIR Task ID if an open question was generated"
    )
    ai_augmentation_delta: str = Field(
        ...,
        description="What AI uniquely detected that rules/thresholds cannot"
    )
