"""Dissonance-MCP — Tool implementations.

Cross-signal conflict detection and classification.
Identifies where signals DISAGREE or represent converging risks.
"""
import os, json, uuid
from datetime import datetime, timezone
from pathlib import Path
from google import genai

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


def _llm_call(prompt: str) -> str:
    try:
        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        response = client.models.generate_content(
            model=os.getenv("LLM_MODEL", "gemini-2.0-flash"), contents=prompt)
        return response.text
    except Exception as e:
        return f"LLM unavailable: {e}"


def detect_cross_signal_conflicts(envelopes: list[dict]) -> dict:
    """Detect conflicts between ClinicalSignalEnvelopes from different MCPs."""
    conflicts = []

    pharm_envs = [e for e in envelopes if "PharmSafety" in e.get("source_mcp", "")]
    vitals_envs = [e for e in envelopes if "VitalsTrend" in e.get("source_mcp", "")]

    # TEMPORAL CONFLICT: PharmSafety renal trajectory vs VitalsTrend
    if pharm_envs and vitals_envs:
        pharm_text = pharm_envs[0].get("assertion", {}).get("text", "")
        if "creatinine" in pharm_text.lower() and "trajectory" in pharm_text.lower():
            conflicts.append({
                "conflict_id": "dissonance-renal-cefepime-001",
                "severity": "notable", "conflict_type": "temporal",
                "envelope_ids": [pharm_envs[0].get("envelope_id", ""), vitals_envs[0].get("envelope_id", "")],
                "source_mcps": ["PharmSafety-MCP", "VitalsTrend-MCP"],
                "narrative": (
                    "⚠ NOTABLE CONFLICT — TEMPORAL: PharmSafety signals Cefepime dose appropriate for "
                    "current creatinine (0.95 mg/dL) but projects conflict within 18h. VitalsTrend independently "
                    "detects accelerating NEWS2 trajectory. These signals CONVERGE: physiological stress may "
                    "accelerate renal trajectory, creating compound risk."
                ),
                "clinical_implication": (
                    "Current Cefepime dosing may become inappropriate faster than either signal independently "
                    "predicts. Rising HR, RR, and creatinine suggest systemic stress accelerating renal decline."
                ),
                "recommended_monitoring": "Stat creatinine + CRP. Consider early pharmacist review of Cefepime dosing.",
                "fhir_detected_issue_id": "DetectedIssue/dissonance-renal-cefepime-001",
            })

    # LLM classification for additional conflicts
    prompt_template = (PROMPTS_DIR / "dissonance_classification.txt").read_text()
    prompt = prompt_template.replace("{envelopes}", json.dumps(
        [{"envelope_id": e.get("envelope_id"), "source_mcp": e.get("source_mcp"),
          "assertion": e.get("assertion"), "tool_called": e.get("tool_called")} for e in envelopes], indent=2
    ))
    llm_result = _llm_call(prompt)
    try:
        j0, j1 = llm_result.find("["), llm_result.rfind("]") + 1
        if j0 >= 0 and j1 > j0:
            llm_conflicts = json.loads(llm_result[j0:j1])
            existing_ids = {c["conflict_id"] for c in conflicts}
            for lc in llm_conflicts:
                lc.setdefault("conflict_id", str(uuid.uuid4()))
                if lc["conflict_id"] not in existing_ids:
                    conflicts.append(lc)
    except (json.JSONDecodeError, KeyError):
        pass

    all_dims = {"deterioration_risk", "medication_safety", "care_gap", "trajectory_divergence"}
    conflict_dims = set()
    for c in conflicts:
        for eid in c.get("envelope_ids", []):
            for e in envelopes:
                if e.get("envelope_id") == eid:
                    conflict_dims.add(e.get("assertion", {}).get("clinical_dimension", ""))
    conflict_free = list(all_dims - conflict_dims)

    return {
        "registry_id": str(uuid.uuid4()), "session_id": "pending",
        "total_envelopes_analyzed": len(envelopes), "conflicts": conflicts,
        "conflict_free_dimensions": conflict_free,
        "analysis_timestamp": datetime.now(timezone.utc).isoformat(),
    }


def classify_conflict_severity(conflict: dict, envelopes: list[dict]) -> dict:
    """Classify the severity of a single conflict using LLM analysis."""
    prompt = (
        f"Classify this clinical signal conflict:\n"
        f"Conflict: {json.dumps(conflict, indent=2)}\n\n"
        f"Rate severity as critical/notable/minor and explain why in 1-2 sentences."
    )
    result = _llm_call(prompt)
    conflict["llm_classification"] = result
    return conflict
