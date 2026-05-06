"""CTIB Pydantic Schemas — SHARP Context Token.

SHARP (Secure Healthcare Agent Runtime Protocol) context token
manages patient context, consent, and scope-based access control
across the agent boundary.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from pydantic import BaseModel, Field


def _default_expiry() -> str:
    """Default token expiry: 4 hours from now."""
    return (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()


class SHARPContextToken(BaseModel):
    """SHARP v1.0 context token for secure agent communication.

    This token is minted at the start of a CTIB session and propagated
    through every agent boundary. It ensures:
    - Patient context is never leaked outside escrow
    - Each agent only sees scopes it needs
    - Full audit trail of context access
    """
    sharp_version: str = Field(default="1.0")
    session_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Escrow session ID"
    )
    fhir_base_url: str = Field(
        default="http://localhost:8080/fhir",
        description="FHIR server base URL"
    )
    patient_id: str = Field(..., description="FHIR Patient resource ID")
    encounter_id: str = Field(..., description="FHIR Encounter resource ID")
    purpose_of_use: str = Field(
        default="CARE_TRANSITION",
        description="Purpose of use code"
    )
    requesting_clinician: str = Field(
        ..., description="Practitioner resource ID"
    )
    context_scope: list[str] = Field(
        default_factory=lambda: [
            "patient/MedicationRequest.read",
            "patient/Observation.read",
            "patient/Condition.read",
            "patient/DocumentReference.read",
            "patient/DiagnosticReport.read",
            "patient/Encounter.read",
            "patient/AllergyIntolerance.read",
        ]
    )
    consent_reference: Optional[str] = Field(
        None, description="FHIR Consent resource reference"
    )
    token_expiry: str = Field(
        default_factory=_default_expiry,
        description="ISO 8601 expiry timestamp (default: 4h from mint)"
    )


class SHARPDeliveryToken(BaseModel):
    """Scoped sub-token for delivery to a specific receiving agent."""
    parent_session_id: str
    delivery_token_id: str = Field(
        default_factory=lambda: str(uuid.uuid4())
    )
    receiving_agent_id: str
    permitted_sections: list[str] = Field(
        default_factory=lambda: [
            "TrajectorySignalSection",
            "OpenQuestionsSection",
            "DissonanceRegistry",
            "WatchSignalSection",
        ]
    )
    expiry: Optional[str] = None
