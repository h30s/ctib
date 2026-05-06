"""PopulationSignal-MCP — Tool implementations.

Trajectory archetype matching. Deterministic archetype lookup — no LLM.
"""
import uuid
from datetime import datetime, timezone

# Hardcoded archetype database for demo
ARCHETYPES = [
    {
        "id": "arch-post-cabg-ckd-001",
        "name": "Post-CABG with CKD — Standard Recovery",
        "profile": {"age_range": [60, 75], "conditions": ["232717009", "433144002"], "gender": "female"},
        "expected_news2_day5": 2.0, "expected_news2_range": [0, 3],
        "expected_cr_trajectory": "stable_0.7_to_1.0",
        "complication_rate": 0.18, "readmission_30d": 0.12,
        "description": "Standard recovery trajectory for post-CABG female patients aged 60-75 with CKD Stage 3."
    },
    {
        "id": "arch-post-cabg-ckd-inflam-002",
        "name": "Post-CABG with CKD + Inflammatory Complication",
        "profile": {"age_range": [60, 75], "conditions": ["232717009", "433144002", "3238004"], "gender": "female"},
        "expected_news2_day5": 4.0, "expected_news2_range": [3, 6],
        "expected_cr_trajectory": "rising_0.8_to_1.4",
        "complication_rate": 0.35, "readmission_30d": 0.22,
        "description": "Post-CABG with concurrent inflammatory process (pericarditis)."
    },
    {
        "id": "arch-post-cabg-dm-003",
        "name": "Post-CABG with T2DM — Metabolic Recovery",
        "profile": {"age_range": [55, 70], "conditions": ["232717009", "44054006"], "gender": "female"},
        "expected_news2_day5": 2.5, "expected_news2_range": [1, 4],
        "expected_cr_trajectory": "stable_0.6_to_0.9",
        "complication_rate": 0.15, "readmission_30d": 0.10,
        "description": "Post-CABG diabetic patients with controlled metabolic status."
    },
    {
        "id": "arch-post-cabg-elderly-004",
        "name": "Post-CABG Elderly — Extended ICU",
        "profile": {"age_range": [70, 85], "conditions": ["232717009"], "gender": "any"},
        "expected_news2_day5": 3.0, "expected_news2_range": [2, 5],
        "expected_cr_trajectory": "variable",
        "complication_rate": 0.28, "readmission_30d": 0.18,
        "description": "Elderly post-CABG patients requiring extended ICU monitoring."
    },
    {
        "id": "arch-post-cabg-uncomplicated-005",
        "name": "Post-CABG — Uncomplicated Recovery",
        "profile": {"age_range": [45, 65], "conditions": ["232717009"], "gender": "any"},
        "expected_news2_day5": 1.0, "expected_news2_range": [0, 2],
        "expected_cr_trajectory": "stable_0.6_to_0.9",
        "complication_rate": 0.08, "readmission_30d": 0.06,
        "description": "Uncomplicated post-CABG with rapid recovery trajectory."
    },
]


def _match_score(patient_profile: dict, archetype: dict) -> float:
    arch_p = archetype["profile"]
    score, total = 0.0, 0.0
    total += 1.0
    age = patient_profile.get("age", 67)
    if arch_p["age_range"][0] <= age <= arch_p["age_range"][1]:
        score += 1.0
    total += 0.5
    if arch_p["gender"] == "any" or arch_p["gender"] == patient_profile.get("gender", "female"):
        score += 0.5
    patient_conditions = set(patient_profile.get("condition_codes", []))
    arch_conditions = set(arch_p.get("conditions", []))
    if arch_conditions:
        total += 2.0
        overlap = len(patient_conditions & arch_conditions)
        score += 2.0 * (overlap / len(arch_conditions))
    return score / total if total > 0 else 0


def match_trajectory_archetype(
    patient_age: int, patient_gender: str,
    condition_codes: list[str], current_news2: int,
) -> dict:
    """Match patient against population trajectory archetypes. Deterministic."""
    patient_profile = {"age": patient_age, "gender": patient_gender, "condition_codes": condition_codes}
    scored = [(round(_match_score(patient_profile, a), 4), a) for a in ARCHETYPES]
    scored.sort(key=lambda x: -x[0])
    best_match = scored[0]
    best_arch = best_match[1]
    expected_range = best_arch["expected_news2_range"]
    if expected_range[1] > expected_range[0]:
        percentile = (current_news2 - expected_range[0]) / (expected_range[1] - expected_range[0])
        percentile = max(0, min(1, percentile)) * 100
    else:
        percentile = 50.0
    above_expected = current_news2 > best_arch["expected_news2_day5"]
    assertion_text = (
        f"Patient matches archetype '{best_arch['name']}' (similarity: {best_match[0]:.0%}). "
        f"Current NEWS2 ({current_news2}) is {'above' if above_expected else 'within'} expected range "
        f"{expected_range} for this archetype at Day 5. "
        f"Percentile position: {percentile:.0f}th. "
        f"Historical complication rate: {best_arch['complication_rate']:.0%}. "
        f"30-day readmission rate: {best_arch['readmission_30d']:.0%}."
    )
    return {
        "envelope_id": str(uuid.uuid4()), "source_mcp": "PopulationSignal-MCP | v1.0",
        "tool_called": "match_trajectory_archetype",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "patient_context_token": "escrow-ref",
        "assertion": {"text": assertion_text, "clinical_dimension": "trajectory_divergence", "direction": "elevated" if above_expected else "stable", "magnitude": percentile / 100.0},
        "confidence_interval": {"lower": max(0, (percentile - 15) / 100.0), "upper": min(1.0, (percentile + 15) / 100.0), "basis": "archetype_population_benchmarking", "calibration_anchor": "STS_CABG_outcomes_database"},
        "evidence_sources": [{"fhir_resource_type": "Patient", "fhir_resource_id": "pt-maria-chen-001", "description": f"Matched against {len(ARCHETYPES)} population archetypes"}],
        "conflicting_signals": [], "open_question_generated": None,
        "ai_augmentation_delta": "Population-level trajectory benchmarking contextualizes individual patient trajectory within historical cohort outcomes.",
        "_archetype_match": {"id": best_arch["id"], "name": best_arch["name"], "similarity": best_match[0], "percentile": percentile},
    }
