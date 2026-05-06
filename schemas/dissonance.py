"""CTIB Pydantic Schemas — Dissonance Registry.

Models for cross-signal conflict detection and classification.
The DissonanceRegistry is the centerpiece of CTIB's epistemic honesty —
it surfaces where different clinical signals DISAGREE rather than
trying to resolve them.
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ConflictSeverity(str, Enum):
    CRITICAL = "critical"
    NOTABLE = "notable"
    MINOR = "minor"


class ConflictType(str, Enum):
    DIRECTIONAL = "directional"       # Signals point opposite directions
    CONFIDENCE = "confidence"         # Same direction, incompatible certainty
    TEMPORAL = "temporal"             # Both correct NOW but will conflict in forecast window
    EVIDENTIAL = "evidential"         # Based on different evidence quality levels


class ClassifiedConflict(BaseModel):
    """A single classified conflict between clinical signals."""
    conflict_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    severity: ConflictSeverity
    conflict_type: ConflictType
    envelope_ids: list[str] = Field(
        ..., description="IDs of conflicting ClinicalSignalEnvelopes"
    )
    source_mcps: list[str] = Field(
        ..., description="Names of MCP servers involved"
    )
    narrative: str = Field(
        ..., description="Human-readable conflict description preserving uncertainty"
    )
    clinical_implication: str = Field(
        ..., description="What this conflict means for patient care"
    )
    recommended_monitoring: Optional[str] = Field(
        None, description="Suggested monitoring action"
    )
    fhir_detected_issue_id: Optional[str] = Field(
        None, description="FHIR DetectedIssue resource ID"
    )


class DissonanceRegistry(BaseModel):
    """Registry of all cross-signal conflicts detected by Dissonance-MCP.

    This registry is NEVER collapsible in the UI — it must always be
    prominently displayed to the receiving clinician.
    """
    registry_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    total_envelopes_analyzed: int
    conflicts: list[ClassifiedConflict] = Field(default_factory=list)
    conflict_free_dimensions: list[str] = Field(
        default_factory=list,
        description="Dimensions where no conflicts were detected"
    )
    analysis_timestamp: str

    @property
    def has_critical(self) -> bool:
        return any(c.severity == ConflictSeverity.CRITICAL for c in self.conflicts)

    @property
    def has_notable(self) -> bool:
        return any(c.severity == ConflictSeverity.NOTABLE for c in self.conflicts)
