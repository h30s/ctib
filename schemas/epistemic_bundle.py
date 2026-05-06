"""CTIB Pydantic Schemas — Epistemic Handoff Bundle.

The final output of the CTIB pipeline: a FHIR Composition resource
containing 4 mandatory sections that transfer clinical reasoning state
during care transitions.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field


class FHIRCoding(BaseModel):
    system: Optional[str] = None
    code: str
    display: str


class FHIRCodeableConcept(BaseModel):
    coding: list[FHIRCoding] = Field(default_factory=list)


class FHIRReference(BaseModel):
    reference: str
    display: Optional[str] = None


class FHIRNarrative(BaseModel):
    status: str = "generated"
    div: str


class CompositionSection(BaseModel):
    """A section of the FHIR Composition."""
    title: str
    code: FHIRCodeableConcept
    text: Optional[FHIRNarrative] = None
    entry: list[FHIRReference] = Field(default_factory=list)


class FHIRTask(BaseModel):
    """A FHIR Task resource representing an open clinical question."""
    resourceType: str = "Task"
    id: str = Field(default_factory=lambda: f"task-{uuid.uuid4().hex[:8]}")
    status: str = "requested"
    intent: str = "plan"
    priority: str = "routine"
    description: str
    for_patient: FHIRReference = Field(alias="for")
    reason_reference: Optional[FHIRReference] = Field(None, alias="reasonReference")
    source_quote: Optional[str] = Field(
        None, description="Exact quote from clinical document"
    )

    model_config = {"populate_by_name": True}


class FHIRSubscription(BaseModel):
    """A FHIR Subscription resource for monitoring."""
    resourceType: str = "Subscription"
    id: str = Field(default_factory=lambda: f"sub-{uuid.uuid4().hex[:8]}")
    status: str = "requested"
    reason: str
    criteria: str
    channel_type: str = "rest-hook"
    end: Optional[str] = None


class FHIRAuditEvent(BaseModel):
    """A FHIR AuditEvent for provenance tracking."""
    resourceType: str = "AuditEvent"
    id: str = Field(default_factory=lambda: f"audit-{uuid.uuid4().hex[:8]}")
    type_code: str
    action: str
    recorded: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    agent_name: str
    entity_reference: str
    outcome: str = "0"  # Success


class EpistemicHandoffBundle(BaseModel):
    """FHIR Composition — the complete Epistemic Handoff Bundle.

    Contains 4 mandatory sections:
    1. TrajectorySignalSection — synthesized clinical trajectory
    2. OpenQuestionsSection — orphaned intentions as FHIR Tasks
    3. DissonanceRegistry — signal conflicts (NEVER collapsible)
    4. WatchSignalSection — monitoring subscriptions
    """
    resourceType: str = "Composition"
    id: str = Field(default_factory=lambda: f"ctib-handoff-{uuid.uuid4().hex[:8]}")
    meta: dict[str, Any] = Field(default_factory=lambda: {
        "profile": ["https://ctib.ai/fhir/StructureDefinition/EpistemicHandoffBundle"]
    })
    status: str = "final"
    type: FHIRCodeableConcept = Field(default_factory=lambda: FHIRCodeableConcept(
        coding=[FHIRCoding(
            system="http://loinc.org",
            code="18842-5",
            display="Discharge summary"
        )]
    ))
    subject: FHIRReference
    encounter: FHIRReference
    date: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    author: list[FHIRReference] = Field(default_factory=lambda: [
        FHIRReference(reference="Device/CTIB-ContextBrokerAgent-v1")
    ])
    title: str = "CTIB Epistemic Handoff Bundle"

    # The 4 mandatory sections
    trajectory_section: Optional[CompositionSection] = None
    open_questions_section: Optional[CompositionSection] = None
    dissonance_section: Optional[CompositionSection] = None
    watch_section: Optional[CompositionSection] = None

    # Embedded data (not strictly FHIR but needed for demo rendering)
    trajectory_narrative: Optional[str] = None
    open_questions: list[FHIRTask] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    subscriptions: list[FHIRSubscription] = Field(default_factory=list)
    audit_events: list[FHIRAuditEvent] = Field(default_factory=list)
    signal_envelopes: list[dict[str, Any]] = Field(default_factory=list)
    sharp_session_id: Optional[str] = None

    def to_fhir_composition(self) -> dict[str, Any]:
        """Export as a FHIR-compliant Composition JSON."""
        sections = []
        if self.trajectory_section:
            sections.append(self.trajectory_section.model_dump())
        if self.open_questions_section:
            sections.append(self.open_questions_section.model_dump())
        if self.dissonance_section:
            sections.append(self.dissonance_section.model_dump())
        if self.watch_section:
            sections.append(self.watch_section.model_dump())

        return {
            "resourceType": self.resourceType,
            "id": self.id,
            "meta": self.meta,
            "status": self.status,
            "type": self.type.model_dump(),
            "subject": self.subject.model_dump(),
            "encounter": self.encounter.model_dump(),
            "date": self.date,
            "author": [a.model_dump() for a in self.author],
            "title": self.title,
            "section": sections,
        }
