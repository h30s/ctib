# CTIB — Clinical Transition Intelligence Bus

> **Epistemic Handoff Agent System for Care Transitions**

CTIB transfers clinical *reasoning state* — not just data — during care transitions. It orchestrates a swarm of **5 MCP constraint servers** and **3 A2A agents** to synthesize structured FHIR data + unstructured clinical notes into a FHIR-native **EpistemicHandoffBundle**.

## Architecture

```
Clinician UI → SwarmOrchestratorAgent → ContextBrokerAgent (SHARP escrow)
                    ↓ (parallel)
    ┌───────────────┼───────────────────────────┐
    ↓               ↓               ↓           ↓
PharmSafety   VitalsTrend    NarrativeSemant  PopulationSignal
    └───────────────┼───────────────────────────┘
                    ↓
              Dissonance-MCP (cross-signal conflict detection)
                    ↓
           LLM Trajectory Synthesis
                    ↓
        TransitionDeliveryAgent → StepDown Receiving Agent (A2A)
```

### Components

| Component | Type | LLM? | Description |
|---|---|---|---|
| ContextBrokerAgent | A2A Agent | ❌ Zero LLM | Privacy spine — SHARP escrow, bundle assembly |
| SwarmOrchestratorAgent | A2A Agent | ✅ Synthesis only | Pipeline director — coordinates MCP swarm |
| TransitionDeliveryAgent | A2A Agent | ❌ Zero LLM | A2A courier — delivers to receiving agents |
| PharmSafety-MCP | MCP Server | ✅ Drug-trajectory | Medication reconciliation + nephrotoxic detection |
| VitalsTrend-MCP | MCP Server | ✅ Deterioration | NEWS2 scoring + subtle deterioration detection |
| NarrativeSemant-MCP | MCP Server | ✅ Core AI | Clinical NLP + orphaned intention detection |
| PopulationSignal-MCP | MCP Server | ❌ Deterministic | Trajectory archetype matching |
| Dissonance-MCP | MCP Server | ✅ Classification | Cross-signal conflict detection |

## Quick Start

### 1. Prerequisites
- Python 3.11+
- Docker (for HAPI FHIR server)
- Gemini API key

### 2. Setup
```bash
cd ctib
cp .env.example .env
# Edit .env and set your GEMINI_API_KEY

pip install -e .
```

### 3. Start HAPI FHIR Server
```bash
docker compose up -d
# Wait for health check: GET http://localhost:8080/fhir/metadata
```

### 4. Seed Patient Data
```bash
python seed_fhir.py
# Seeds ~97 FHIR resources for Maria Chen
```

### 5. Run CTIB
```bash
python main.py
# Dashboard: http://localhost:9000
# API Docs:  http://localhost:9000/docs
```

### 6. Run Tests
```bash
python -m pytest tests/ -v
```

## The Demo — Maria Chen

**Maria Chen, 67F, Day 5 post-op CABG, ICU → Step-down transfer at 2:14 AM.**

Three critical findings the system surfaces:

1. **Orphaned Intention** — "Will revisit CRP trend" never followed up; rheumatology consult never formalized
2. **Temporal Dissonance** — Cefepime dose OK for current creatinine but renal trajectory predicts conflict in 12-18h
3. **Watch Subscriptions** — Auto-generated FHIR Subscriptions for creatinine threshold monitoring

## API Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/api/run-ctib` | Execute full Golden Path pipeline |
| GET | `/api/session/{id}` | Get session status |
| GET | `/api/bundle/{id}` | Get assembled bundle |
| GET | `/api/audit` | Get FHIR AuditEvent trail |
| GET | `/api/health` | Health check |
| GET | `/.well-known/agent-card.json` | A2A agent discovery |

## Technology

- **Runtime**: Python 3.11+ / FastAPI / Uvicorn
- **FHIR**: HAPI FHIR JPA Server (Docker)
- **LLM**: Google Gemini (via google-genai SDK)
- **Protocols**: MCP SDK, A2A, SHARP, FHIR R4
- **Data**: 100% synthetic — zero PHI

## License

Built for the **Agents Assemble** hackathon on Prompt Opinion Marketplace.

## Team 

Himanshu Soni
Tushar Gupta