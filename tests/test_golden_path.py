"""CTIB Golden Path End-to-End Test.

Tests the full Maria Chen workflow without requiring HAPI FHIR server.
Uses mock FHIR data to verify the complete pipeline:
SHARP → MCP Swarm → Dissonance → Synthesis → Bundle Assembly → Delivery
"""
import sys
import json
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# Ensure ctib root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from schemas.clinical_signal_envelope import ClinicalSignalEnvelope, ClinicalDimension
from schemas.sharp_context import SHARPContextToken, SHARPDeliveryToken
from schemas.epistemic_bundle import EpistemicHandoffBundle, FHIRTask, FHIRSubscription
from schemas.dissonance import DissonanceRegistry, ClassifiedConflict, ConflictSeverity, ConflictType
from agents.context_broker import ContextBrokerAgent
from agents.transition_delivery import TransitionDeliveryAgent, StepDownReceivingAgent


# ─── Fixtures ───

def load_seed_data():
    """Load all seed data from JSON files."""
    seed_dir = Path(__file__).parent.parent / "data" / "seed"
    data = {}
    for f in seed_dir.glob("*.json"):
        with open(f) as fp:
            data[f.stem] = json.load(fp)
    return data


def make_sharp_token():
    return SHARPContextToken(
        patient_id="pt-maria-chen-001",
        encounter_id="enc-icu-day5",
        requesting_clinician="practitioner-dr-kim-001",
        consent_reference="Consent/maria-chen-consent-001",
    )


# ─── Schema Tests ───

class TestSchemas:
    def test_clinical_signal_envelope_creation(self):
        env = ClinicalSignalEnvelope(
            source_mcp="TestMCP | v1.0",
            tool_called="test_tool",
            patient_context_token="escrow-123",
            assertion={
                "text": "Test assertion",
                "clinical_dimension": "medication_safety",
                "direction": "elevated",
                "magnitude": 0.5,
            },
            confidence_interval={
                "lower": 0.4, "upper": 0.6,
                "basis": "test", "calibration_anchor": "test_anchor",
            },
            ai_augmentation_delta="Test AI delta",
        )
        assert env.envelope_id is not None
        assert env.source_mcp == "TestMCP | v1.0"
        assert env.assertion.clinical_dimension == ClinicalDimension.MEDICATION_SAFETY

    def test_sharp_token_defaults(self):
        token = make_sharp_token()
        assert token.sharp_version == "1.0"
        assert token.purpose_of_use == "CARE_TRANSITION"
        assert len(token.context_scope) == 7
        assert "patient/Observation.read" in token.context_scope

    def test_sharp_delivery_token(self):
        dt = SHARPDeliveryToken(
            parent_session_id="test-session",
            receiving_agent_id="test-agent",
        )
        assert dt.delivery_token_id is not None
        assert len(dt.permitted_sections) == 4

    def test_dissonance_registry(self):
        conflict = ClassifiedConflict(
            severity=ConflictSeverity.NOTABLE,
            conflict_type=ConflictType.TEMPORAL,
            envelope_ids=["env-1", "env-2"],
            source_mcps=["PharmSafety-MCP", "VitalsTrend-MCP"],
            narrative="Test conflict",
            clinical_implication="Test implication",
        )
        registry = DissonanceRegistry(
            session_id="test",
            total_envelopes_analyzed=5,
            conflicts=[conflict],
            conflict_free_dimensions=["care_gap"],
            analysis_timestamp="2026-05-02T02:14:33Z",
        )
        assert registry.has_notable is True
        assert registry.has_critical is False


# ─── ContextBrokerAgent Tests ───

class TestContextBroker:
    def test_register_sharp_context(self):
        broker = ContextBrokerAgent()
        token = make_sharp_token()
        session_id = broker.register_sharp_context(token)
        assert session_id == token.session_id
        assert session_id in broker.sessions

    def test_authorize_signal_exchange(self):
        broker = ContextBrokerAgent()
        token = make_sharp_token()
        session_id = broker.register_sharp_context(token)

        # Should pass — requesting subset of available scopes
        assert broker.authorize_signal_exchange(
            session_id, "TestAgent", ["patient/Observation.read"]
        ) is True

        # Should fail — requesting scope not in token
        assert broker.authorize_signal_exchange(
            session_id, "TestAgent", ["patient/Procedure.write"]
        ) is False

    def test_deposit_and_assemble(self):
        broker = ContextBrokerAgent()
        token = make_sharp_token()
        session_id = broker.register_sharp_context(token)

        # Deposit a signal
        envelope = {
            "envelope_id": "test-env-001",
            "source_mcp": "TestMCP | v1.0",
            "assertion": {"text": "Test", "clinical_dimension": "medication_safety",
                          "direction": "elevated", "magnitude": 0.5},
        }
        broker.deposit_signal(session_id, envelope)

        # Deposit dissonance
        broker.deposit_dissonance(session_id, {
            "registry_id": "test-reg",
            "conflicts": [],
            "conflict_free_dimensions": ["medication_safety"],
        })

        # Deposit open questions
        broker.deposit_open_questions(session_id, [
            {"id": "task-crp-001", "description": "CRP monitoring",
             "for": {"reference": "Patient/pt-maria-chen-001"},
             "reasonReference": {"reference": "DocumentReference/doc-progress-day3"}}
        ])

        # Deposit subscriptions
        broker.deposit_subscriptions(session_id, [
            {"id": "watch-cr-001", "reason": "Creatinine watch",
             "criteria": "Observation?code=2160-0&value-quantity=gt1.2"}
        ])

        # Deposit trajectory
        broker.deposit_trajectory(session_id, "Test trajectory narrative")

        # Assemble bundle
        bundle = broker.assemble_epistemic_bundle(session_id)
        assert bundle["resourceType"] == "Composition"
        assert bundle["trajectory_section"] is not None
        assert bundle["open_questions_section"] is not None
        assert bundle["dissonance_section"] is not None
        assert bundle["watch_section"] is not None
        assert bundle["trajectory_narrative"] == "Test trajectory narrative"

    def test_authorize_delivery(self):
        broker = ContextBrokerAgent()
        token = make_sharp_token()
        session_id = broker.register_sharp_context(token)

        dt = broker.authorize_delivery(session_id, "stepdown-agent-001")
        assert dt["parent_session_id"] == session_id
        assert dt["receiving_agent_id"] == "stepdown-agent-001"

    def test_audit_trail(self):
        broker = ContextBrokerAgent()
        token = make_sharp_token()
        session_id = broker.register_sharp_context(token)
        assert len(broker.audit_log) >= 1
        assert broker.audit_log[0].action == "REGISTER"


# ─── MCP Server Tests (Direct Function Calls) ───

class TestMCPServers:
    def test_pharmsafety_reconcile(self):
        from mcp_servers.pharmsafety.tools import reconcile_medications
        seed = load_seed_data()

        result = reconcile_medications(
            medication_requests=seed.get("medications", []),
            allergies=seed.get("allergies", []),
            conditions=seed.get("conditions", []),
            lab_observations=[],  # No labs file pregenerated
        )
        assert result["source_mcp"] == "PharmSafety-MCP | v1.0"
        assert result["assertion"]["clinical_dimension"] == "medication_safety"
        assert result["envelope_id"] is not None

    def test_vitalstrend_news2(self):
        from mcp_servers.vitalstrend.tools import compute_news2_trajectory

        # Create minimal vital signs
        vitals = []
        hr_values = [78, 80, 84, 86, 88, 90, 92, 94]
        rr_values = [16, 17, 18, 18, 19, 20, 21, 22]
        timestamps = [
            "2026-04-30T08:00:00Z", "2026-04-30T14:00:00Z",
            "2026-04-30T20:00:00Z", "2026-05-01T02:00:00Z",
            "2026-05-01T08:00:00Z", "2026-05-01T14:00:00Z",
            "2026-05-01T20:00:00Z", "2026-05-02T02:00:00Z",
        ]
        for i, ts in enumerate(timestamps):
            vitals.append({
                "effectiveDateTime": ts,
                "code": {"coding": [{"code": "8867-4"}]},
                "valueQuantity": {"value": hr_values[i]},
            })
            vitals.append({
                "effectiveDateTime": ts,
                "code": {"coding": [{"code": "9279-1"}]},
                "valueQuantity": {"value": rr_values[i]},
            })
            vitals.append({
                "effectiveDateTime": ts,
                "code": {"coding": [{"code": "8480-6"}]},
                "valueQuantity": {"value": 120},
            })
            vitals.append({
                "effectiveDateTime": ts,
                "code": {"coding": [{"code": "2708-6"}]},
                "valueQuantity": {"value": 95},
            })
            vitals.append({
                "effectiveDateTime": ts,
                "code": {"coding": [{"code": "8310-5"}]},
                "valueQuantity": {"value": 37.1},
            })

        result = compute_news2_trajectory(vital_observations=vitals, time_window_hours=48)
        assert result["source_mcp"] == "VitalsTrend-MCP | v1.0"
        assert result["assertion"]["clinical_dimension"] == "deterioration_risk"
        # NEWS2 should show elevated direction (scores increasing)
        assert result["assertion"]["direction"] == "elevated"
        # Should have NEWS2 details
        assert len(result["_news2_details"]) == 8

    def test_vitalstrend_watch_subscriptions(self):
        from mcp_servers.vitalstrend.tools import generate_watch_subscriptions

        subs = generate_watch_subscriptions(open_questions=[], dissonance_conflicts=[])
        assert len(subs) == 3
        sub_ids = [s["id"] for s in subs]
        assert "watch-creatinine-001" in sub_ids
        assert "watch-crp-001" in sub_ids
        assert "watch-rr-001" in sub_ids

    def test_populationsignal_archetype(self):
        from mcp_servers.populationsignal.tools import match_trajectory_archetype

        result = match_trajectory_archetype(
            patient_age=67, patient_gender="female",
            condition_codes=["232717009", "433144002", "44054006", "3238004"],
            current_news2=4,
        )
        assert result["source_mcp"] == "PopulationSignal-MCP | v1.0"
        assert result["assertion"]["clinical_dimension"] == "trajectory_divergence"
        # Should match the inflammatory archetype
        assert "archetype" in result["assertion"]["text"].lower()

    def test_dissonance_detection(self):
        from mcp_servers.dissonance.tools import detect_cross_signal_conflicts

        envelopes = [
            {
                "envelope_id": "env-pharm-001",
                "source_mcp": "PharmSafety-MCP | v1.0",
                "tool_called": "reconcile_medications",
                "assertion": {
                    "text": "TEMPORAL RISK: Cefepime active with creatinine trending upward. Trajectory modeling suggests conflict.",
                    "clinical_dimension": "medication_safety",
                    "direction": "elevated", "magnitude": 0.85,
                },
            },
            {
                "envelope_id": "env-vitals-001",
                "source_mcp": "VitalsTrend-MCP | v1.0",
                "tool_called": "compute_news2_trajectory",
                "assertion": {
                    "text": "NEWS2 trajectory elevated",
                    "clinical_dimension": "deterioration_risk",
                    "direction": "elevated", "magnitude": 0.57,
                },
            },
        ]

        result = detect_cross_signal_conflicts(envelopes=envelopes)
        assert result["total_envelopes_analyzed"] == 2
        # Should detect the temporal conflict between PharmSafety and VitalsTrend
        assert len(result["conflicts"]) >= 1
        temporal_conflicts = [c for c in result["conflicts"] if c.get("conflict_type") == "temporal"]
        assert len(temporal_conflicts) >= 1

    def test_narrativesemant_uncertainty(self):
        from mcp_servers.narrativesemant.tools import detect_uncertainty_language
        import base64

        docs = [{
            "id": "doc-test",
            "type": {"coding": [{"display": "Progress note"}]},
            "content": [{"attachment": {
                "data": base64.b64encode(b"Will revisit if CRP continues to trend. Cannot fully exclude pericarditis.").decode()
            }}],
        }]
        result = detect_uncertainty_language(documents=docs)
        assert result["source_mcp"] == "NarrativeSemant-MCP | v1.0"
        assert result["tool_called"] == "detect_uncertainty_language"
        assert result["assertion"]["clinical_dimension"] == "care_gap"
        assert "_markers" in result


# ─── TransitionDeliveryAgent Tests ───

class TestTransitionDelivery:
    def test_stepdown_agent_card(self):
        agent = StepDownReceivingAgent()
        card = agent.get_agent_card()
        assert "ClinicalSignalEnvelope-v1" in card["schema_support"]
        assert "EpistemicHandoffBundle-v1" in card["schema_support"]

    def test_stepdown_receive_bundle(self):
        agent = StepDownReceivingAgent()
        task = {
            "params": {
                "id": "task-001",
                "message": {
                    "parts": [{
                        "type": "data",
                        "data": {
                            "bundle": {
                                "id": "test-bundle",
                                "trajectory_section": {"title": "TrajectorySignal"},
                                "open_questions_section": {"title": "OpenQuestions"},
                                "dissonance_section": {"title": "DissonanceRegistry"},
                                "watch_section": {"title": "WatchSignals"},
                            },
                        }
                    }]
                }
            }
        }
        result = agent.receive_bundle(task)
        assert result["status"] == "accepted"
        assert len(result["sections_received"]) == 4

    async def test_delivery_flow(self):
        broker = ContextBrokerAgent()
        token = make_sharp_token()
        session_id = broker.register_sharp_context(token)

        # Setup minimal session data
        broker.deposit_signal(session_id, {
            "envelope_id": "env-001",
            "source_mcp": "TestMCP",
            "assertion": {"text": "Test"},
        })
        broker.deposit_dissonance(session_id, {"conflicts": [], "registry_id": "test"})
        broker.deposit_open_questions(session_id, [])
        broker.deposit_subscriptions(session_id, [])
        broker.deposit_trajectory(session_id, "Test trajectory")

        delivery = TransitionDeliveryAgent(context_broker=broker)
        result = await delivery.deliver(session_id)

        assert result["status"] == "delivered"
        assert result["session_id"] == session_id
        assert result["receiving_agent"] == "stepdown-receiving-agent-001"


# ─── SHARP Token Propagation Test ───

class TestSHARPPropagation:
    def test_sharp_flows_through_pipeline(self):
        """Verify SHARP token propagates correctly through all agent boundaries."""
        broker = ContextBrokerAgent()
        token = make_sharp_token()

        # Register
        session_id = broker.register_sharp_context(token)
        assert broker.sessions[session_id]["token"].patient_id == "pt-maria-chen-001"

        # Authorize
        assert broker.authorize_signal_exchange(
            session_id, "SwarmOrchestrator",
            ["patient/Observation.read", "patient/Condition.read"]
        ) is True

        # Deposit
        broker.deposit_signal(session_id, {"envelope_id": "e1", "source_mcp": "test"})
        broker.deposit_dissonance(session_id, {"conflicts": [], "registry_id": "r1"})
        broker.deposit_open_questions(session_id, [])
        broker.deposit_subscriptions(session_id, [])
        broker.deposit_trajectory(session_id, "Narrative")

        # Assemble
        bundle = broker.assemble_epistemic_bundle(session_id)
        assert bundle["sharp_session_id"] == session_id
        assert bundle["subject"]["reference"] == "Patient/pt-maria-chen-001"
        assert bundle["encounter"]["reference"] == "Encounter/enc-icu-day5"

        # Delivery token
        dt = broker.authorize_delivery(session_id, "receiver")
        assert dt["parent_session_id"] == session_id

        # Audit trail completeness
        actions = [e.action for e in broker.audit_log]
        assert "REGISTER" in actions
        assert "AUTHORIZE" in actions
        assert "DEPOSIT_SIGNAL" in actions
        assert "ASSEMBLE_BUNDLE" in actions
        assert "AUTHORIZE_DELIVERY" in actions


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
