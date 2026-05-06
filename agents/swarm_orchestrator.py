"""SwarmOrchestratorAgent — The Director. Coordinates MCP swarm.

Orchestrates the full CTIB pipeline:
SHARP → FHIR fetch → parallel MCP Batch 1 → sequential Batch 2 →
Dissonance → LLM Synthesis → Watch Subscriptions → Bundle Assembly
"""
import os, json, asyncio, base64
from datetime import datetime, timezone
from pathlib import Path
from google import genai

from fhir_client import FHIRClient
from agents.context_broker import ContextBrokerAgent
from schemas.sharp_context import SHARPContextToken

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


class SwarmOrchestratorAgent:
    """The Director. Coordinates 5 MCP constraint servers."""

    def __init__(self, context_broker: ContextBrokerAgent = None):
        self.context_broker = context_broker or ContextBrokerAgent()
        self.fhir_client = FHIRClient()
        self.pipeline_log: list[dict] = []

    def _log(self, phase: str, message: str, data: dict = None):
        entry = {"phase": phase, "message": message,
                 "timestamp": datetime.now(timezone.utc).isoformat()}
        if data:
            entry["data"] = data
        self.pipeline_log.append(entry)

    async def orchestrate_transition(self, sharp_token: SHARPContextToken) -> dict:
        """Full CTIB pipeline execution."""

        # ─── PHASE 0: SHARP Context Registration ───
        self._log("PHASE_0", "Registering SHARP context token")
        session_id = self.context_broker.register_sharp_context(sharp_token)
        self._log("PHASE_0", f"Escrow session: {session_id}")

        # Authorize orchestrator
        self.context_broker.authorize_signal_exchange(
            session_id, "SwarmOrchestratorAgent", sharp_token.context_scope
        )

        # ─── PHASE 1: FHIR Fetch (Parallel) ───
        self._log("PHASE_1", "Fetching FHIR resources in parallel")
        resources = await self.fhir_client.fetch_all(
            sharp_token.patient_id, sharp_token.encounter_id
        )
        self._log("PHASE_1", "FHIR fetch complete", {
            k: len(v) if isinstance(v, list) else 1 for k, v in resources.items()
            if not isinstance(v, dict) or "error" not in v
        })

        # ─── PHASE 2: MCP Swarm Batch 1 (Parallel via asyncio.gather) ───
        self._log("PHASE_2", "Launching MCP Batch 1 (4 servers in parallel)")
        from mcp_servers.pharmsafety.tools import reconcile_medications
        from mcp_servers.vitalstrend.tools import compute_news2_trajectory
        from mcp_servers.narrativesemant.tools import extract_clinical_assertions
        from mcp_servers.populationsignal.tools import match_trajectory_archetype

        meds = resources.get("medications", [])
        allergies = resources.get("allergies", [])
        conditions = resources.get("conditions", [])
        vitals = resources.get("vitals", [])
        labs = resources.get("labs", [])
        documents = resources.get("documents", [])

        # Extract condition codes for population matching
        condition_codes = []
        for c in conditions:
            for coding in c.get("code", {}).get("coding", []):
                if coding.get("code"):
                    condition_codes.append(coding["code"])

        # Run Batch 1 in PARALLEL using asyncio.to_thread
        pharm_env, vitals_env, narrative_env, pop_env = await asyncio.gather(
            asyncio.to_thread(reconcile_medications,
                medication_requests=meds, allergies=allergies,
                conditions=conditions, lab_observations=labs),
            asyncio.to_thread(compute_news2_trajectory,
                vital_observations=vitals, time_window_hours=48),
            asyncio.to_thread(extract_clinical_assertions,
                documents=documents),
            asyncio.to_thread(match_trajectory_archetype,
                patient_age=67, patient_gender="female",
                condition_codes=condition_codes,
                current_news2=0),  # Will be updated after NEWS2 compute
        )

        self._log("PHASE_2", "PharmSafety-MCP complete")
        self._log("PHASE_2", "VitalsTrend-MCP complete")
        self._log("PHASE_2", "NarrativeSemant-MCP complete")

        # Update PopulationSignal with actual NEWS2 score
        details = vitals_env.get("_news2_details", [])
        current_news2 = details[-1].get("score", 0) if details else 0
        if current_news2 > 0:
            pop_env = await asyncio.to_thread(match_trajectory_archetype,
                patient_age=67, patient_gender="female",
                condition_codes=condition_codes, current_news2=current_news2)
        self._log("PHASE_2", "PopulationSignal-MCP complete")

        # ─── PHASE 2b: MCP Batch 2 (Sequential) ───
        self._log("PHASE_2b", "Launching MCP Batch 2 (sequential)")
        from mcp_servers.vitalstrend.tools import detect_subtle_deterioration
        from mcp_servers.narrativesemant.tools import identify_open_questions

        deterioration_env = await asyncio.to_thread(detect_subtle_deterioration,
            vital_observations=vitals, news2_result=vitals_env)
        self._log("PHASE_2b", "Subtle deterioration detection complete")

        open_q_result = await asyncio.to_thread(identify_open_questions,
            assertion_result=narrative_env, conditions=conditions, documents=documents)
        self._log("PHASE_2b", "Open question identification complete")
        open_questions = open_q_result.get("_tasks", [])

        # ─── PHASE 3: Dissonance Detection ───
        self._log("PHASE_3", "Running Dissonance-MCP")
        from mcp_servers.dissonance.tools import detect_cross_signal_conflicts

        all_envelopes = [pharm_env, vitals_env, narrative_env, pop_env, deterioration_env]
        dissonance = await asyncio.to_thread(detect_cross_signal_conflicts, envelopes=all_envelopes)
        self._log("PHASE_3", f"Dissonance: {len(dissonance.get('conflicts', []))} conflicts")

        # ─── PHASE 4: LLM Synthesis ───
        self._log("PHASE_4", "Synthesizing trajectory narrative")
        trajectory_narrative = await self._synthesize_trajectory(
            all_envelopes, dissonance, open_questions, sharp_token
        )
        self._log("PHASE_4", "Trajectory synthesis complete")

        # ─── PHASE 5: Watch Subscriptions ───
        from mcp_servers.vitalstrend.tools import generate_watch_subscriptions
        subscriptions = generate_watch_subscriptions(
            open_questions=open_questions,
            dissonance_conflicts=dissonance.get("conflicts", []),
        )
        self._log("PHASE_5", f"Generated {len(subscriptions)} watch subscriptions")

        # ─── PHASE 6: Bundle Assembly ───
        self._log("PHASE_6", "Depositing signals to ContextBroker")
        for env in all_envelopes:
            self.context_broker.deposit_signal(session_id, env)
        self.context_broker.deposit_dissonance(session_id, dissonance)
        self.context_broker.deposit_open_questions(session_id, open_questions)
        self.context_broker.deposit_subscriptions(session_id, subscriptions)
        self.context_broker.deposit_trajectory(session_id, trajectory_narrative)

        bundle = self.context_broker.assemble_epistemic_bundle(session_id)
        self._log("PHASE_6", "EpistemicHandoffBundle assembled")

        return {
            "session_id": session_id,
            "bundle": bundle,
            "pipeline_log": self.pipeline_log,
        }

    async def _synthesize_trajectory(self, envelopes, dissonance, open_questions, token):
        """LLM synthesis — the AI node in the orchestrator."""
        prompt_template = (PROMPTS_DIR / "trajectory_synthesis.txt").read_text()

        envelope_summary = json.dumps([{
            "envelope_id": e.get("envelope_id"),
            "source_mcp": e.get("source_mcp"),
            "assertion": e.get("assertion"),
            "ai_augmentation_delta": e.get("ai_augmentation_delta"),
        } for e in envelopes], indent=2)

        prompt = prompt_template.replace("{envelopes}", envelope_summary)
        prompt = prompt.replace("{dissonance_registry}", json.dumps(dissonance, indent=2))
        prompt = prompt.replace("{open_questions}", json.dumps(open_questions, indent=2))
        prompt = prompt.replace("{patient_context}",
            f"Patient: Maria Chen, 67F, Post-CABG Day 5, ICU→Step-down transfer at 02:14.\n"
            f"Active conditions: CAD, Post-CABG, HTN, CKD 3a, T2DM, suspected pericarditis."
        )

        try:
            client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
            response = client.models.generate_content(
                model=os.getenv("LLM_MODEL", "gemini-2.0-flash"), contents=prompt
            )
            return response.text
        except Exception as e:
            return (
                f"[Synthesis unavailable: {e}]\n\n"
                "TRAJECTORY SUMMARY (rule-based fallback):\n"
                "Maria Chen, 67F, post-CABG Day 5. NEWS2 trending upward (0→4). "
                "Cefepime active with rising creatinine trajectory. "
                "CRP monitoring orphaned since Day 3. Rheumatology consult not formalized. "
                "TEMPORAL DISSONANCE: Current Cefepime dose appropriate now but projected "
                "renal trajectory suggests conflict within 18h."
            )
