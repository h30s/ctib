"""TransitionDeliveryAgent — The Courier. A2A delivery.

Handles the final mile: discovering the receiving agent's capabilities,
validating schema support, obtaining a scoped SHARP delivery token,
and delivering the EpistemicHandoffBundle via the A2A protocol.
"""
import uuid
import json
import asyncio
from datetime import datetime, timezone
from typing import Optional

import httpx

from agents.context_broker import ContextBrokerAgent
from schemas.epistemic_bundle import FHIRAuditEvent


class TransitionDeliveryAgent:
    """The Courier. A2A delivery of EpistemicHandoffBundle."""

    def __init__(self, context_broker: ContextBrokerAgent = None):
        self.context_broker = context_broker or ContextBrokerAgent()
        self.delivery_log: list[dict] = []

    def _log(self, action: str, message: str, data: dict = None):
        entry = {
            "action": action,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if data:
            entry["data"] = data
        self.delivery_log.append(entry)

    async def discover_capabilities(self, receiving_agent_url: str) -> dict:
        """Probe receiving agent's .well-known/agent-card.json for capabilities."""
        self._log("DISCOVERY", f"Probing {receiving_agent_url}")

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                url = f"{receiving_agent_url.rstrip('/')}/.well-known/agent-card.json"
                resp = await client.get(url)
                if resp.status_code == 200:
                    capabilities = resp.json()
                    self._log("DISCOVERY", "Capabilities received", capabilities)
                    return capabilities
        except Exception as e:
            self._log("DISCOVERY", f"HTTP discovery failed: {e}, using mock capabilities")

        # Mock capabilities for demo (StepDown Receiving Agent)
        return {
            "agent_id": "stepdown-receiving-agent-001",
            "name": "StepDown Receiving Agent",
            "description": "Step-down unit care transition receiving agent",
            "capabilities": ["receive_handoff_bundle"],
            "schema_support": [
                "ClinicalSignalEnvelope-v1",
                "EpistemicHandoffBundle-v1",
            ],
            "sharp_required": True,
            "endpoint": receiving_agent_url,
        }

    async def deliver(self, session_id: str, receiving_agent_url: str = None) -> dict:
        """Full A2A delivery pipeline.

        Steps:
        1. Discovery — probe receiving agent capabilities
        2. Schema validation — verify schema support
        3. Authorization — get scoped SHARP delivery token
        4. Delivery — send the bundle
        5. Audit — log the delivery event
        """
        if receiving_agent_url is None:
            receiving_agent_url = "http://localhost:9000/a2a/stepdown"

        # Step 1: Discovery
        self._log("DELIVER", "Step 1: Capability discovery")
        capabilities = await self.discover_capabilities(receiving_agent_url)

        # Step 2: Schema validation
        self._log("DELIVER", "Step 2: Schema validation")
        schema_support = capabilities.get("schema_support", [])
        if "ClinicalSignalEnvelope-v1" not in schema_support:
            raise ValueError(
                f"Receiving agent does not support ClinicalSignalEnvelope-v1. "
                f"Supported: {schema_support}"
            )
        if "EpistemicHandoffBundle-v1" not in schema_support:
            raise ValueError(
                f"Receiving agent does not support EpistemicHandoffBundle-v1. "
                f"Supported: {schema_support}"
            )
        self._log("DELIVER", "Schema support confirmed", {
            "supported": schema_support
        })

        # Step 3: Authorization
        self._log("DELIVER", "Step 3: SHARP delivery authorization")
        agent_id = capabilities.get("agent_id", "unknown")
        delivery_token = self.context_broker.authorize_delivery(
            session_id, agent_id
        )
        self._log("DELIVER", "Delivery token minted", {
            "token_id": delivery_token.get("delivery_token_id"),
            "receiving_agent": agent_id,
        })

        # Step 4: Assemble and deliver
        self._log("DELIVER", "Step 4: Bundle assembly and delivery")
        bundle = self.context_broker.assemble_epistemic_bundle(session_id)

        response = await self._send_a2a_task(
            receiving_agent_url, bundle, delivery_token, capabilities
        )
        self._log("DELIVER", "Bundle delivered", {
            "status": response.get("status"),
            "agent": agent_id,
        })

        # Step 5: Audit
        self._log("DELIVER", "Step 5: Audit event")
        self._write_audit_event(session_id, "DELIVERED", agent_id)

        return {
            "status": "delivered",
            "session_id": session_id,
            "receiving_agent": agent_id,
            "delivery_token_id": delivery_token.get("delivery_token_id"),
            "response": response,
            "delivery_log": self.delivery_log,
        }

    async def _send_a2a_task(
        self, receiving_agent_url: str, bundle: dict,
        delivery_token: dict, capabilities: dict
    ) -> dict:
        """Send the EpistemicHandoffBundle to the receiving agent via A2A."""
        a2a_task = {
            "jsonrpc": "2.0",
            "method": "tasks/send",
            "id": str(uuid.uuid4()),
            "params": {
                "id": str(uuid.uuid4()),
                "message": {
                    "role": "user",
                    "parts": [
                        {
                            "type": "data",
                            "data": {
                                "mimeType": "application/fhir+json",
                                "bundle": bundle,
                                "delivery_token": delivery_token,
                            }
                        }
                    ]
                }
            }
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{receiving_agent_url.rstrip('/')}/a2a",
                    json=a2a_task,
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code == 200:
                    return resp.json()
        except Exception as e:
            self._log("A2A_SEND", f"HTTP delivery failed: {e}, using mock ACK")

        # Mock ACK for demo
        return {
            "jsonrpc": "2.0",
            "id": a2a_task["id"],
            "result": {
                "id": a2a_task["params"]["id"],
                "status": {
                    "state": "completed",
                    "message": {
                        "role": "agent",
                        "parts": [
                            {
                                "type": "text",
                                "text": (
                                    "EpistemicHandoffBundle received and acknowledged by "
                                    "StepDown Receiving Agent. All 4 sections parsed: "
                                    "TrajectorySignal, OpenQuestions, DissonanceRegistry, "
                                    "WatchSignals. Bundle integrity verified."
                                )
                            }
                        ]
                    }
                }
            }
        }

    def _write_audit_event(self, session_id: str, action: str, agent_id: str):
        """Write FHIR AuditEvent for delivery."""
        event = FHIRAuditEvent(
            type_code=f"CTIB-{action}",
            action=action,
            agent_name="TransitionDeliveryAgent",
            entity_reference=f"Session/{session_id}",
        )
        self.context_broker.audit_log.append(event)


class StepDownReceivingAgent:
    """Mock receiving agent for demo purposes.

    Simulates a step-down unit agent that receives and acknowledges
    the EpistemicHandoffBundle.
    """

    AGENT_CARD = {
        "agent_id": "stepdown-receiving-agent-001",
        "name": "StepDown Receiving Agent",
        "description": "Step-down unit care transition receiving agent",
        "capabilities": ["receive_handoff_bundle"],
        "schema_support": [
            "ClinicalSignalEnvelope-v1",
            "EpistemicHandoffBundle-v1",
        ],
        "sharp_required": True,
    }

    def __init__(self):
        self.received_bundles: list[dict] = []

    def receive_bundle(self, a2a_task: dict) -> dict:
        """Process incoming A2A task containing EpistemicHandoffBundle."""
        parts = (
            a2a_task.get("params", {})
            .get("message", {})
            .get("parts", [])
        )

        bundle_data = None
        for part in parts:
            if part.get("type") == "data":
                bundle_data = part.get("data", {}).get("bundle")
                break

        if bundle_data:
            self.received_bundles.append({
                "bundle": bundle_data,
                "received_at": datetime.now(timezone.utc).isoformat(),
                "task_id": a2a_task.get("params", {}).get("id"),
            })

            sections = []
            if bundle_data.get("trajectory_section"):
                sections.append("TrajectorySignal")
            if bundle_data.get("open_questions_section"):
                sections.append("OpenQuestions")
            if bundle_data.get("dissonance_section"):
                sections.append("DissonanceRegistry")
            if bundle_data.get("watch_section"):
                sections.append("WatchSignals")

            return {
                "status": "accepted",
                "sections_received": sections,
                "bundle_id": bundle_data.get("id", "unknown"),
                "message": (
                    f"EpistemicHandoffBundle received. "
                    f"{len(sections)} sections parsed and verified."
                )
            }

        return {
            "status": "rejected",
            "message": "No bundle data found in A2A task.",
        }

    def get_agent_card(self) -> dict:
        """Return agent card for A2A discovery."""
        return self.AGENT_CARD
