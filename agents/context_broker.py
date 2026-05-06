"""ContextBrokerAgent — The Privacy Spine. ZERO LLM inference.

Entirely deterministic. Manages SHARP token escrow, scope-based authorization,
signal deposit, and EpistemicHandoffBundle assembly.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from schemas.clinical_signal_envelope import ClinicalSignalEnvelope
from schemas.sharp_context import SHARPContextToken, SHARPDeliveryToken
from schemas.epistemic_bundle import (
    EpistemicHandoffBundle, CompositionSection, FHIRCoding,
    FHIRCodeableConcept, FHIRNarrative, FHIRReference, FHIRAuditEvent,
)


class ContextBrokerAgent:
    """The Privacy Spine. ZERO LLM inference.

    Manages:
    - SHARP context token registration and escrow
    - Scope-based authorization for agent signal exchange
    - Signal deposit into escrow slots
    - EpistemicHandoffBundle assembly from deposited signals
    - FHIR AuditEvent generation for full provenance
    - Scoped delivery token minting
    """

    def __init__(self):
        self.sessions: dict[str, dict] = {}
        self.audit_log: list[FHIRAuditEvent] = []

    def register_sharp_context(self, token: SHARPContextToken) -> str:
        """Register SHARP token, return escrow session ID."""
        session_id = token.session_id
        self.sessions[session_id] = {
            "token": token,
            "signals": [],
            "dissonance": None,
            "open_questions": [],
            "subscriptions": [],
            "trajectory_narrative": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "active",
        }
        self._write_audit("REGISTER", "ContextBrokerAgent",
                          f"Session/{session_id}", session_id)
        return session_id

    def authorize_signal_exchange(self, session_id: str, agent_id: str,
                                   required_scopes: list[str]) -> bool:
        """Check if agent's required scopes are within SHARP token scopes."""
        session = self.sessions.get(session_id)
        if not session or session["status"] != "active":
            return False

        token = session["token"]
        available = set(token.context_scope)
        required = set(required_scopes)
        authorized = required.issubset(available)

        self._write_audit(
            "AUTHORIZE" if authorized else "DENY",
            agent_id,
            f"Session/{session_id}",
            session_id,
        )
        return authorized

    def deposit_signal(self, session_id: str, envelope: dict):
        """Store signal envelope in escrow slot."""
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        session["signals"].append(envelope)
        self._write_audit("DEPOSIT_SIGNAL", envelope.get("source_mcp", "unknown"),
                          f"Envelope/{envelope.get('envelope_id', 'unknown')}", session_id)

    def deposit_dissonance(self, session_id: str, dissonance: dict):
        """Store dissonance registry."""
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        session["dissonance"] = dissonance
        self._write_audit("DEPOSIT_DISSONANCE", "Dissonance-MCP",
                          f"DissonanceRegistry/{dissonance.get('registry_id', 'unknown')}", session_id)

    def deposit_open_questions(self, session_id: str, tasks: list[dict]):
        """Store open question FHIR Tasks."""
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        session["open_questions"] = tasks

    def deposit_subscriptions(self, session_id: str, subs: list[dict]):
        """Store watch subscriptions."""
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        session["subscriptions"] = subs

    def deposit_trajectory(self, session_id: str, narrative: str):
        """Store synthesized trajectory narrative."""
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        session["trajectory_narrative"] = narrative

    def assemble_epistemic_bundle(self, session_id: str) -> dict:
        """Join all deposited signals under patient context.

        Build FHIR Composition with 4 mandatory sections.
        Write FHIR AuditEvent.
        """
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        token = session["token"]

        # Section 1: TrajectorySignalSection
        trajectory_section = CompositionSection(
            title="TrajectorySignalSection",
            code=FHIRCodeableConcept(coding=[
                FHIRCoding(code="CTIB-001", display="Synthesized Trajectory")
            ]),
            text=FHIRNarrative(
                div=session.get("trajectory_narrative", "No trajectory synthesized.")
            ),
            entry=[FHIRReference(reference=f"DocumentReference/signal-env-{i}")
                   for i in range(len(session["signals"]))],
        )

        # Section 2: OpenQuestionsSection
        open_q_section = CompositionSection(
            title="OpenQuestionsSection",
            code=FHIRCodeableConcept(coding=[
                FHIRCoding(code="CTIB-002", display="Open Clinical Questions")
            ]),
            entry=[FHIRReference(reference=f"Task/{t.get('id', 'unknown')}")
                   for t in session["open_questions"]],
        )

        # Section 3: DissonanceRegistry — NEVER COLLAPSIBLE
        dissonance = session.get("dissonance", {})
        conflicts = dissonance.get("conflicts", [])
        dissonance_text = ""
        for c in conflicts:
            severity_icon = "🔴" if c.get("severity") == "critical" else "🟡"
            dissonance_text += (
                f"{severity_icon} {c.get('severity', '').upper()} CONFLICT — "
                f"{c.get('conflict_type', '').upper()}: {c.get('narrative', '')}\n\n"
            )
        if not dissonance_text:
            dissonance_text = "No cross-signal conflicts detected."

        dissonance_section = CompositionSection(
            title="DissonanceRegistry",
            code=FHIRCodeableConcept(coding=[
                FHIRCoding(code="CTIB-003", display="Signal Conflicts — NEVER COLLAPSIBLE")
            ]),
            text=FHIRNarrative(div=dissonance_text),
            entry=[FHIRReference(reference=f"DetectedIssue/{c.get('conflict_id', 'unknown')}")
                   for c in conflicts],
        )

        # Section 4: WatchSignalSection
        watch_section = CompositionSection(
            title="WatchSignalSection",
            code=FHIRCodeableConcept(coding=[
                FHIRCoding(code="CTIB-004", display="Monitoring Protocol")
            ]),
            entry=[FHIRReference(reference=f"Subscription/{s.get('id', 'unknown')}")
                   for s in session["subscriptions"]],
        )

        bundle = EpistemicHandoffBundle(
            subject=FHIRReference(reference=f"Patient/{token.patient_id}"),
            encounter=FHIRReference(reference=f"Encounter/{token.encounter_id}"),
            title=f"CTIB Epistemic Handoff Bundle — ICU to Step-Down",
            trajectory_section=trajectory_section,
            open_questions_section=open_q_section,
            dissonance_section=dissonance_section,
            watch_section=watch_section,
            trajectory_narrative=session.get("trajectory_narrative"),
            open_questions=session["open_questions"],
            conflicts=conflicts,
            subscriptions=session["subscriptions"],
            audit_events=[a.model_dump() for a in self.audit_log],
            signal_envelopes=session["signals"],
            sharp_session_id=session_id,
        )

        self._write_audit("ASSEMBLE_BUNDLE", "ContextBrokerAgent",
                          f"Composition/{bundle.id}", session_id)

        return bundle.model_dump()

    def authorize_delivery(self, session_id: str, receiving_agent: str) -> dict:
        """Mint a scoped delivery SHARP sub-token for the receiving agent."""
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        delivery_token = SHARPDeliveryToken(
            parent_session_id=session_id,
            receiving_agent_id=receiving_agent,
        )

        self._write_audit("AUTHORIZE_DELIVERY", "ContextBrokerAgent",
                          f"DeliveryToken/{delivery_token.delivery_token_id}", session_id)

        return delivery_token.model_dump()

    def _write_audit(self, action: str, agent: str, entity: str, session_id: str):
        """Write FHIR AuditEvent."""
        event = FHIRAuditEvent(
            type_code=f"CTIB-{action}",
            action=action,
            agent_name=agent,
            entity_reference=entity,
        )
        self.audit_log.append(event)

    def get_session_status(self, session_id: str) -> Optional[dict]:
        """Get current session status."""
        session = self.sessions.get(session_id)
        if not session:
            return None
        return {
            "session_id": session_id,
            "status": session["status"],
            "signals_deposited": len(session["signals"]),
            "has_dissonance": session["dissonance"] is not None,
            "open_questions_count": len(session["open_questions"]),
            "subscriptions_count": len(session["subscriptions"]),
            "has_trajectory": session["trajectory_narrative"] is not None,
            "audit_events": len(self.audit_log),
        }
