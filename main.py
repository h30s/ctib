"""CTIB — Main FastAPI Application.

Clinical Transition Intelligence Bus API server.
Exposes the full Golden Path pipeline as REST endpoints
and serves the demo UI dashboard.
"""
import os
import sys
import json
import asyncio
from pathlib import Path
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import uvicorn

# Ensure ctib is on the path
sys.path.insert(0, str(Path(__file__).parent))

load_dotenv()

from schemas.sharp_context import SHARPContextToken
from agents.context_broker import ContextBrokerAgent
from agents.swarm_orchestrator import SwarmOrchestratorAgent
from agents.transition_delivery import TransitionDeliveryAgent, StepDownReceivingAgent

app = FastAPI(
    title="CTIB — Clinical Transition Intelligence Bus",
    description="Epistemic Handoff Agent System for Care Transitions",
    version="1.0.0",
)

# CORS: use ALLOWED_ORIGINS env var in production, defaults to * for dev
_origins = os.getenv("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Shared state
context_broker = ContextBrokerAgent()
orchestrator = SwarmOrchestratorAgent(context_broker=context_broker)
delivery_agent = TransitionDeliveryAgent(context_broker=context_broker)
stepdown_agent = StepDownReceivingAgent()

# Store results for retrieval
results_store: dict[str, dict] = {}

# Serve static files
STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ─── Health Check ───

@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "CTIB",
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "gemini_configured": bool(os.getenv("GEMINI_API_KEY")),
        "fhir_mode": "mock" if os.getenv("FHIR_MOCK_MODE", "").lower() in ("true", "1") else "live",
        "fhir_base": os.getenv("FHIR_BASE_URL", "http://localhost:8080/fhir"),
    }


# ─── Run Full CTIB Pipeline ───

@app.post("/api/run-ctib")
async def run_ctib(
    patient_id: str = "pt-maria-chen-001",
    encounter_id: str = "enc-icu-day5",
):
    """Execute the full CTIB Golden Path pipeline.

    Steps:
    1. Mint SHARP context token
    2. Register with ContextBroker
    3. Fetch FHIR resources
    4. Run MCP swarm (5 servers)
    5. LLM trajectory synthesis
    6. Assemble EpistemicHandoffBundle
    7. A2A delivery to receiving agent
    """
    try:
        # Create SHARP token
        sharp_token = SHARPContextToken(
            patient_id=patient_id,
            encounter_id=encounter_id,
            requesting_clinician="practitioner-dr-kim-001",
            consent_reference=f"Consent/{patient_id.replace('pt-', '')}-consent-001",
            fhir_base_url=os.getenv("FHIR_BASE_URL", "http://localhost:8080/fhir"),
        )

        # Fresh agent instances per run to prevent cross-session contamination
        broker = ContextBrokerAgent()
        orch = SwarmOrchestratorAgent(context_broker=broker)
        courier = TransitionDeliveryAgent(context_broker=broker)

        # Run orchestration pipeline
        result = await orch.orchestrate_transition(sharp_token)
        session_id = result["session_id"]

        # A2A delivery
        delivery_result = await courier.deliver(session_id)
        result["delivery"] = delivery_result

        # Store for retrieval
        results_store[session_id] = result

        return {
            "status": "success",
            "session_id": session_id,
            "bundle": result["bundle"],
            "delivery": delivery_result,
            "pipeline_log": result["pipeline_log"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        import traceback
        traceback.print_exc()  # Log to server console, not to client
        raise HTTPException(
            status_code=500,
            detail={
                "error": str(e),
            }
        )


# ─── Session Status ───

@app.get("/api/session/{session_id}")
async def get_session(session_id: str):
    """Get current session status."""
    status = context_broker.get_session_status(session_id)
    if not status:
        raise HTTPException(status_code=404, detail="Session not found")
    return status


# ─── Bundle Retrieval ───

@app.get("/api/bundle/{session_id}")
async def get_bundle(session_id: str):
    """Get the assembled EpistemicHandoffBundle for a session."""
    result = results_store.get(session_id)
    if not result:
        raise HTTPException(status_code=404, detail="No result for this session")
    return result["bundle"]


# ─── Pipeline Log ───

@app.get("/api/log/{session_id}")
async def get_pipeline_log(session_id: str):
    """Get the pipeline execution log."""
    result = results_store.get(session_id)
    if not result:
        raise HTTPException(status_code=404, detail="No result for this session")
    return result.get("pipeline_log", [])


# ─── Audit Trail ───

@app.get("/api/audit")
async def get_audit_trail():
    """Get the full FHIR AuditEvent trail."""
    return [e.model_dump() for e in context_broker.audit_log]


# ─── A2A Endpoints ───

@app.get("/a2a/stepdown/.well-known/agent-card.json")
async def stepdown_agent_card():
    """A2A agent card discovery for StepDown receiving agent."""
    return stepdown_agent.get_agent_card()


@app.post("/a2a/stepdown/a2a")
async def stepdown_receive(task: dict):
    """A2A task receiving endpoint for StepDown agent."""
    result = stepdown_agent.receive_bundle(task)
    return {
        "jsonrpc": "2.0",
        "id": task.get("id"),
        "result": {
            "id": task.get("params", {}).get("id"),
            "status": {
                "state": "completed" if result["status"] == "accepted" else "failed",
                "message": {
                    "role": "agent",
                    "parts": [{"type": "text", "text": result["message"]}]
                }
            }
        }
    }


# ─── CTIB Agent Card ───

@app.get("/.well-known/agent-card.json")
async def ctib_agent_card():
    """A2A agent card for CTIB SwarmOrchestrator."""
    card_path = Path(__file__).parent / ".well-known" / "agent-card.json"
    if card_path.exists():
        return json.loads(card_path.read_text())
    return {
        "name": "CTIB SwarmOrchestrator",
        "description": "Clinical Transition Intelligence Bus — Epistemic Handoff Agent",
        "supportedInterfaces": ["A2A", "REST"],
        "defaultInputModes": ["json"],
        "defaultOutputModes": ["json"],
        "capabilities": {},
        "skills": [
            {
                "id": "orchestrate_transition_analysis",
                "name": "orchestrate_transition_analysis",
                "description": "Orchestrates transition analysis",
                "tags": ["healthcare", "orchestration", "handoff"]
            }
        ],
        "schema_support": [
            "ClinicalSignalEnvelope-v1",
            "EpistemicHandoffBundle-v1",
        ],
        "sharp_required": True,
        "url": f"http://localhost:{os.getenv('CTIB_PORT', 9000)}",
    }


# ─── Serve UI ───

@app.get("/")
async def serve_ui():
    """Serve the demo dashboard."""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>CTIB — Run <code>npm run build</code> or see /api/health</h1>")


# ─── Main ───

def main():
    # Railway injects PORT; CTIB_PORT is our own fallback
    port = int(os.getenv("PORT", os.getenv("CTIB_PORT", 9000)))
    fhir_mode = "MOCK (seed files)" if os.getenv("FHIR_MOCK_MODE", "").lower() in ("true", "1") else "LIVE"
    print(f"\n{'='*60}")
    print(f"  CTIB — Clinical Transition Intelligence Bus")
    print(f"  Dashboard: http://localhost:{port}")
    print(f"  API Docs:  http://localhost:{port}/docs")
    print(f"  Health:    http://localhost:{port}/api/health")
    print(f"  FHIR Mode: {fhir_mode}")
    print(f"  Gemini:    {'configured' if os.getenv('GEMINI_API_KEY') else 'NOT SET'}")
    print(f"{'='*60}\n")
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
