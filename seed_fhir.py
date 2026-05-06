"""Generate all FHIR seed data for Maria Chen and seed to HAPI FHIR server."""
import os
import base64
import json
import sys
import httpx
from dotenv import load_dotenv

load_dotenv()

FHIR_BASE = os.getenv("FHIR_BASE_URL", "http://localhost:8080/fhir")

VITALS_DATA = [
    {"ts": "2026-04-30T08:00:00Z", "hr": 78, "sbp": 128, "dbp": 72, "rr": 16, "temp": 37.0, "spo2": 96},
    {"ts": "2026-04-30T14:00:00Z", "hr": 80, "sbp": 130, "dbp": 74, "rr": 17, "temp": 37.1, "spo2": 96},
    {"ts": "2026-04-30T20:00:00Z", "hr": 84, "sbp": 126, "dbp": 70, "rr": 18, "temp": 37.2, "spo2": 95},
    {"ts": "2026-05-01T02:00:00Z", "hr": 86, "sbp": 124, "dbp": 68, "rr": 18, "temp": 37.3, "spo2": 95},
    {"ts": "2026-05-01T08:00:00Z", "hr": 88, "sbp": 122, "dbp": 70, "rr": 19, "temp": 37.1, "spo2": 95},
    {"ts": "2026-05-01T14:00:00Z", "hr": 90, "sbp": 120, "dbp": 68, "rr": 20, "temp": 37.4, "spo2": 94},
    {"ts": "2026-05-01T20:00:00Z", "hr": 92, "sbp": 118, "dbp": 66, "rr": 21, "temp": 37.2, "spo2": 94},
    {"ts": "2026-05-02T02:00:00Z", "hr": 94, "sbp": 116, "dbp": 66, "rr": 22, "temp": 37.3, "spo2": 94},
]

VITAL_CODES = [
    ("8867-4", "Heart rate", "hr", "/min"),
    ("8480-6", "Systolic blood pressure", "sbp", "mm[Hg]"),
    ("8462-4", "Diastolic blood pressure", "dbp", "mm[Hg]"),
    ("9279-1", "Respiratory rate", "rr", "/min"),
    ("8310-5", "Body temperature", "temp", "Cel"),
    ("2708-6", "Oxygen saturation", "spo2", "%"),
]

LABS_DATA = [
    {"ts": "2026-04-27T06:00:00Z", "cr": 0.8, "k": 4.1, "wbc": 8.2, "crp": 5.0, "hgb": 11.2},
    {"ts": "2026-04-28T06:00:00Z", "cr": 0.8, "k": 4.0, "wbc": 9.1, "crp": 12.0, "hgb": 10.8},
    {"ts": "2026-04-29T06:00:00Z", "cr": 0.85, "k": 4.2, "wbc": 10.3, "crp": 18.0, "hgb": 10.5},
    {"ts": "2026-04-30T06:00:00Z", "cr": 0.88, "k": 4.3, "wbc": 9.8, "crp": 22.0, "hgb": 10.4},
    {"ts": "2026-05-01T06:00:00Z", "cr": 0.90, "k": 4.1, "wbc": 9.5, "crp": None, "hgb": 10.2},
    {"ts": "2026-05-02T02:00:00Z", "cr": 0.95, "k": 4.4, "wbc": 9.2, "crp": None, "hgb": 10.0},
]

LAB_CODES = [
    ("2160-0", "Creatinine", "cr", "mg/dL"),
    ("2823-3", "Potassium", "k", "meq/L"),
    ("6690-2", "WBC", "wbc", "10*3/uL"),
    ("1988-5", "C reactive protein", "crp", "mg/L"),
    ("718-7", "Hemoglobin", "hgb", "g/dL"),
]

DOCUMENTS = {
    "doc-progress-day3": {
        "type_code": "11506-3", "type_display": "Progress note",
        "date": "2026-04-29T10:00:00Z",
        "text": "Post-op day 3. Patient progressing well s/p CABG x3.\nHemodynamics stable. Weaning O2, currently 2L NC with sat 95%.\n\nLabs: WBC trending up slightly, 10.3 today. CRP 18, up from 12 yesterday.\nInflammatory markers mildly elevated. Discussed briefly with cardiology\nre: post-op pericarditis vs. normal post-surgical inflammatory response.\nWill revisit if CRP continues to trend. Rheumatology not yet formally\nconsulted but may be warranted.\n\nRenal: Creatinine stable at 0.85. Continue current fluid management.\nCefepime day 2 for empiric coverage, cultures pending.\nPlan: Continue current management. Target step-down transfer Day 5."
    },
    "doc-cardiology-day3": {
        "type_code": "11488-4", "type_display": "Consultation note",
        "date": "2026-04-29T14:00:00Z",
        "text": "Reviewed labs: CRP 18, WBC 10.3. Echo Day 2 shows no pericardial\neffusion. EF 55%, no wall motion abnormalities.\n\nAssessment: Inflammatory markers likely normal post-surgical response.\nCannot fully exclude early pericarditis.\n\nRecommend: Trend CRP over next 48-72h. If persistent elevation or\nnew symptoms, consider formal rheumatology consultation and colchicine."
    },
    "doc-nursing-day5": {
        "type_code": "34745-0", "type_display": "Nurse Note",
        "date": "2026-05-02T02:00:00Z",
        "text": "Night shift handoff: Maria Chen, post-op Day 5 CABG.\nDay team plans step-down transfer overnight if bed available.\nVitals trending slightly — HR up from 78 to 92 over 48h, RR 21.\nMD aware, no new orders. Patient reports mild chest discomfort.\nNo new labs ordered tonight. Cefepime due at 02:00."
    },
}


def make_vital_obs(ts_idx, ts, code, display, value, unit):
    return {
        "resourceType": "Observation",
        "id": f"obs-vital-{code}-{ts_idx:02d}",
        "status": "final",
        "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "vital-signs", "display": "Vital Signs"}]}],
        "code": {"coding": [{"system": "http://loinc.org", "code": code, "display": display}]},
        "subject": {"reference": "Patient/pt-maria-chen-001"},
        "encounter": {"reference": "Encounter/enc-icu-day5"},
        "effectiveDateTime": ts,
        "valueQuantity": {"value": value, "unit": unit, "system": "http://unitsofmeasure.org", "code": unit},
    }


def make_lab_obs(ts_idx, ts, code, display, value, unit):
    obs = {
        "resourceType": "Observation",
        "id": f"obs-lab-{code}-{ts_idx:02d}",
        "status": "final",
        "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "laboratory", "display": "Laboratory"}]}],
        "code": {"coding": [{"system": "http://loinc.org", "code": code, "display": display}]},
        "subject": {"reference": "Patient/pt-maria-chen-001"},
        "encounter": {"reference": "Encounter/enc-icu-day5"},
        "effectiveDateTime": ts,
    }
    if value is not None:
        obs["valueQuantity"] = {"value": value, "unit": unit, "system": "http://unitsofmeasure.org", "code": unit}
    else:
        # dataAbsentReason for deliberately missing values (e.g. CRP not drawn)
        obs["dataAbsentReason"] = {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/data-absent-reason", "code": "not-performed", "display": "Not Performed"}]}
    return obs


def make_document_ref(doc_id, info):
    content_b64 = base64.b64encode(info["text"].encode()).decode()
    return {
        "resourceType": "DocumentReference",
        "id": doc_id,
        "status": "current",
        "type": {"coding": [{"system": "http://loinc.org", "code": info["type_code"], "display": info["type_display"]}]},
        "subject": {"reference": "Patient/pt-maria-chen-001"},
        "date": info["date"],
        "content": [{"attachment": {"contentType": "text/plain", "data": content_b64}}],
    }


def build_all_resources():
    """Build all ~97 FHIR resources."""
    resources = []

    # Patient
    with open("data/seed/patient.json") as f:
        resources.append(json.load(f))

    # Encounter
    with open("data/seed/encounter.json") as f:
        resources.append(json.load(f))

    # Conditions
    with open("data/seed/conditions.json") as f:
        resources.extend(json.load(f))

    # Medications
    with open("data/seed/medications.json") as f:
        resources.extend(json.load(f))

    # Allergies
    with open("data/seed/allergies.json") as f:
        resources.extend(json.load(f))

    # Vitals: 8 timepoints × 6 params = 48
    for ts_idx, row in enumerate(VITALS_DATA):
        for code, display, key, unit in VITAL_CODES:
            resources.append(make_vital_obs(ts_idx, row["ts"], code, display, row[key], unit))

    # Labs: 6 timepoints × 5 params = 30 (CRP missing on last 2 uses dataAbsentReason)
    for ts_idx, row in enumerate(LABS_DATA):
        for code, display, key, unit in LAB_CODES:
            val = row[key]
            resources.append(make_lab_obs(ts_idx, row["ts"], code, display, val, unit))

    # Documents: 3
    for doc_id, info in DOCUMENTS.items():
        resources.append(make_document_ref(doc_id, info))

    # DiagnosticReport: 1 (Echo Day 2)
    resources.append({
        "resourceType": "DiagnosticReport",
        "id": "diag-echo-day2",
        "status": "final",
        "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0074", "code": "CUS", "display": "Cardiac Ultrasound"}]}],
        "code": {"coding": [{"system": "http://loinc.org", "code": "42148-7", "display": "US Heart"}], "text": "Echocardiogram"},
        "subject": {"reference": "Patient/pt-maria-chen-001"},
        "encounter": {"reference": "Encounter/enc-icu-day5"},
        "effectiveDateTime": "2026-04-28T10:00:00Z",
        "conclusion": "EF 55%, no pericardial effusion, no wall motion abnormalities.",
        "conclusionCode": [{"coding": [{"system": "http://snomed.info/sct", "code": "399067008", "display": "Normal cardiac function"}]}],
    })

    return resources


def seed_to_fhir(resources):
    """POST resources as a FHIR transaction Bundle."""
    entries = []
    for r in resources:
        rt = r["resourceType"]
        rid = r["id"]
        entries.append({
            "fullUrl": f"{FHIR_BASE}/{rt}/{rid}",
            "resource": r,
            "request": {"method": "PUT", "url": f"{rt}/{rid}"},
        })

    bundle = {"resourceType": "Bundle", "type": "transaction", "entry": entries}

    print(f"Seeding {len(entries)} resources to {FHIR_BASE}...")
    resp = httpx.post(FHIR_BASE, json=bundle, timeout=60)
    if resp.status_code in (200, 201):
        print(f"[OK] Successfully seeded {len(entries)} resources!")
    else:
        print(f"[ERROR] Error {resp.status_code}: {resp.text[:500]}")
        sys.exit(1)

    # Verify
    verify_queries = [
        (f"/Patient/pt-maria-chen-001", "Patient"),
        (f"/Observation?patient=pt-maria-chen-001&category=vital-signs&_summary=count", "Vital Signs"),
        (f"/Observation?patient=pt-maria-chen-001&category=laboratory&_summary=count", "Lab Results"),
        (f"/DocumentReference?patient=pt-maria-chen-001&_summary=count", "Documents"),
    ]
    for path, label in verify_queries:
        r = httpx.get(f"{FHIR_BASE}{path}", timeout=10)
        print(f"  [OK] {label}: {r.status_code}")


def save_seed_files(resources):
    """Also save generated vitals/labs/docs to seed directory."""
    vitals = [r for r in resources if r["resourceType"] == "Observation"
              and any(c.get("code") == "vital-signs" for cat in r.get("category", []) for c in cat.get("coding", []))]
    labs = [r for r in resources if r["resourceType"] == "Observation"
            and any(c.get("code") == "laboratory" for cat in r.get("category", []) for c in cat.get("coding", []))]
    docs = [r for r in resources if r["resourceType"] == "DocumentReference"]

    with open("data/seed/vitals.json", "w") as f:
        json.dump(vitals, f, indent=2)
    with open("data/seed/labs.json", "w") as f:
        json.dump(labs, f, indent=2)
    with open("data/seed/documents.json", "w") as f:
        json.dump(docs, f, indent=2)
    print(f"Saved {len(vitals)} vitals, {len(labs)} labs, {len(docs)} documents to data/seed/")


if __name__ == "__main__":
    resources = build_all_resources()
    print(f"Built {len(resources)} total FHIR resources")
    save_seed_files(resources)

    if "--no-upload" not in sys.argv:
        seed_to_fhir(resources)
    else:
        print("Skipping FHIR upload (--no-upload flag)")
