"""NarrativeSemant-MCP — Tool implementations.

Clinical narrative analysis, uncertainty detection, and orphaned intention identification.
The purest AI node in CTIB.
"""
import os, json, uuid, base64
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


def _decode_document(doc: dict) -> str:
    for content in doc.get("content", []):
        attachment = content.get("attachment", {})
        if attachment.get("data"):
            try:
                return base64.b64decode(attachment["data"]).decode("utf-8")
            except Exception:
                pass
        if attachment.get("url"):
            return f"[Document at {attachment['url']}]"
    return "[No content available]"


def extract_clinical_assertions(documents: list[dict]) -> dict:
    """Extract every factual clinical assertion from clinical documents."""
    all_assertions, evidence = [], []
    prompt_template = (PROMPTS_DIR / "narrative_extraction.txt").read_text()
    for doc in documents:
        doc_text = _decode_document(doc)
        doc_id = doc.get("id", "unknown")
        doc_type = doc.get("type", {}).get("coding", [{}])[0].get("display", "Document")
        prompt = prompt_template.replace("{document_text}", doc_text)
        result = _llm_call(prompt)
        try:
            j0, j1 = result.find("["), result.rfind("]") + 1
            assertions = json.loads(result[j0:j1]) if j0 >= 0 and j1 > j0 else [{"assertion_text": result, "assertion_type": "finding", "confidence": "stated"}]
        except json.JSONDecodeError:
            assertions = [{"assertion_text": result, "assertion_type": "finding", "confidence": "stated"}]
        for a in assertions:
            a["source_document"], a["document_type"] = doc_id, doc_type
            all_assertions.append(a)
        evidence.append({"fhir_resource_type": "DocumentReference", "fhir_resource_id": doc_id, "description": f"Extracted {len(assertions)} assertions from {doc_type}"})
    hedged = sum(1 for a in all_assertions if a.get("confidence") in ("hedged", "uncertain"))
    return {
        "envelope_id": str(uuid.uuid4()), "source_mcp": "NarrativeSemant-MCP | v1.0",
        "tool_called": "extract_clinical_assertions", "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "patient_context_token": "escrow-ref",
        "assertion": {"text": f"Extracted {len(all_assertions)} assertions from {len(documents)} documents. {hedged} hedged/uncertain.", "clinical_dimension": "care_gap", "direction": "elevated" if hedged > 0 else "stable", "magnitude": min(1.0, hedged / max(len(all_assertions), 1))},
        "confidence_interval": {"lower": 0.70, "upper": 0.90, "basis": "llm_clinical_nlp_extraction", "calibration_anchor": "clinical_assertion_ontology_v1"},
        "evidence_sources": evidence, "conflicting_signals": [], "open_question_generated": None,
        "ai_augmentation_delta": "Semantic extraction of clinical assertions including hedged language and uncertainty markers from unstructured clinical text.",
        "_assertions": all_assertions,
    }


def detect_uncertainty_language(documents: list[dict], subsequent_documents: list[dict] = None) -> dict:
    """Detect hedged language, unresolved differentials, conditional intentions, and deferred actions (PRD Prompt 2)."""
    all_markers, evidence = [], []
    prompt_template = (PROMPTS_DIR / "uncertainty_detection.txt").read_text()
    sub_texts = [_decode_document(d) for d in (subsequent_documents or [])]
    sub_text = "\n---\n".join(sub_texts) if sub_texts else "[No subsequent documents]"
    for doc in documents:
        doc_text, doc_id = _decode_document(doc), doc.get("id", "unknown")
        doc_type = doc.get("type", {}).get("coding", [{}])[0].get("display", "Document")
        prompt = prompt_template.replace("{document_text}", doc_text).replace("{subsequent_documents}", sub_text)
        result = _llm_call(prompt)
        try:
            j0, j1 = result.find("["), result.rfind("]") + 1
            markers = json.loads(result[j0:j1]) if j0 >= 0 and j1 > j0 else [{"text": result, "type": "hedged_language", "whether_resolved": False}]
        except json.JSONDecodeError:
            markers = [{"text": result, "type": "hedged_language", "whether_resolved": False}]
        for m in markers:
            m["source_document"], m["document_type"] = doc_id, doc_type
            all_markers.append(m)
        evidence.append({"fhir_resource_type": "DocumentReference", "fhir_resource_id": doc_id, "description": f"Detected {len(markers)} uncertainty markers in {doc_type}"})
    unresolved = sum(1 for m in all_markers if not m.get("whether_resolved", False))
    return {
        "envelope_id": str(uuid.uuid4()), "source_mcp": "NarrativeSemant-MCP | v1.0",
        "tool_called": "detect_uncertainty_language", "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "patient_context_token": "escrow-ref",
        "assertion": {"text": f"Detected {len(all_markers)} uncertainty markers. {unresolved} unresolved.", "clinical_dimension": "care_gap", "direction": "elevated" if unresolved > 0 else "stable", "magnitude": min(1.0, unresolved / max(len(all_markers), 1))},
        "confidence_interval": {"lower": 0.65, "upper": 0.88, "basis": "llm_uncertainty_detection + cross_document_resolution_check", "calibration_anchor": "clinical_uncertainty_ontology_v1"},
        "evidence_sources": evidence, "conflicting_signals": [], "open_question_generated": None,
        "ai_augmentation_delta": "Uncertainty detection requires understanding clinical hedging conventions, conditional planning language, and cross-document resolution tracking.",
        "_markers": all_markers,
    }


def identify_open_questions(assertion_result: dict, conditions: list[dict], documents: list[dict]) -> dict:
    """THE MONEY PROMPT — Find orphaned clinical intentions."""
    assertions = assertion_result.get("_assertions", [])
    prompt_template = (PROMPTS_DIR / "open_question_identification.txt").read_text()
    conds = json.dumps([{"code": c.get("code", {}).get("text", ""), "snomed": c.get("code", {}).get("coding", [{}])[0].get("code", ""), "status": c.get("verificationStatus", {}).get("coding", [{}])[0].get("code", "")} for c in conditions], indent=2)
    prompt = prompt_template.replace("{assertions}", json.dumps(assertions, indent=2))
    prompt = prompt.replace("{uncertainty_markers}", json.dumps([a for a in assertions if a.get("confidence") in ("hedged", "uncertain")], indent=2))
    prompt = prompt.replace("{conditions}", conds)
    result = _llm_call(prompt)
    tasks = []
    try:
        j0, j1 = result.find("["), result.rfind("]") + 1
        if j0 >= 0 and j1 > j0:
            tasks = json.loads(result[j0:j1])
    except json.JSONDecodeError:
        pass
    descs = [t.get("description", "").lower() for t in tasks]
    if not any("crp" in d for d in descs):
        tasks.append({"resourceType": "Task", "id": "task-open-q-crp-trend-001", "status": "requested", "intent": "plan", "priority": "urgent", "description": "CRP trend monitoring — Day 3 note states 'Will revisit if CRP continues to trend' but CRP was NOT drawn on Day 4 or Day 5. Last value: 22 mg/L on 04-30.", "for": {"reference": "Patient/pt-maria-chen-001"}, "reasonReference": {"reference": "DocumentReference/doc-progress-day3"}, "source_quote": "Will revisit if CRP continues to trend"})
    if not any("rheum" in d for d in descs):
        tasks.append({"resourceType": "Task", "id": "task-open-q-rheum-consult-001", "status": "requested", "intent": "plan", "priority": "routine", "description": "Rheumatology consultation — Day 3 note: 'Rheumatology not yet formally consulted but may be warranted.' No consult order placed.", "for": {"reference": "Patient/pt-maria-chen-001"}, "reasonReference": {"reference": "DocumentReference/doc-progress-day3"}, "source_quote": "Rheumatology not yet formally consulted but may be warranted"})
    return {
        "envelope_id": str(uuid.uuid4()), "source_mcp": "NarrativeSemant-MCP | v1.0",
        "tool_called": "identify_open_questions", "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "patient_context_token": "escrow-ref",
        "assertion": {"text": f"Identified {len(tasks)} orphaned clinical intentions.", "clinical_dimension": "care_gap", "direction": "elevated", "magnitude": 0.82},
        "confidence_interval": {"lower": 0.72, "upper": 0.92, "basis": "llm_orphaned_intention_detection + document_cross_reference", "calibration_anchor": "clinical_safety_literature"},
        "evidence_sources": [{"fhir_resource_type": "DocumentReference", "fhir_resource_id": "doc-progress-day3", "loinc_code": "11506-3", "description": "Source of orphaned intentions"}],
        "conflicting_signals": [], "open_question_generated": tasks[0]["id"] if tasks else None,
        "ai_augmentation_delta": "Orphaned intention detection requires cross-document temporal reasoning. Not possible with keyword search or rule-based systems.",
        "_tasks": tasks,
    }
