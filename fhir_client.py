"""Async FHIR client for parallel resource fetching.

Supports two modes:
  1. LIVE MODE (default): Connects to a HAPI FHIR server
  2. MOCK MODE: Reads from data/seed/ JSON files (for Railway/cloud deployment)

Set FHIR_MOCK_MODE=true to use mock mode.
"""
import os
import json
import asyncio
from pathlib import Path
import httpx

FHIR_BASE = os.getenv("FHIR_BASE_URL", "http://localhost:8080/fhir")
SEED_DIR = Path(__file__).parent / "data" / "seed"


def _is_mock_mode() -> bool:
    """Check if FHIR mock mode is enabled."""
    return os.getenv("FHIR_MOCK_MODE", "").lower() in ("true", "1", "yes")


def _load_seed(filename: str):
    """Load a seed JSON file, return empty on failure."""
    path = SEED_DIR / filename
    if path.exists():
        with open(path, "r") as f:
            return json.load(f)
    return [] if filename not in ("patient.json", "encounter.json") else {}


class FHIRClient:
    """Async FHIR client that fetches all resources for a patient in parallel.

    When FHIR_MOCK_MODE=true, returns pre-seeded data from data/seed/
    instead of connecting to a live FHIR server. This enables deployment
    without HAPI FHIR (ideal for Railway/Render free-tier).
    """

    def __init__(self, base_url: str = None):
        self.base_url = base_url or os.getenv("FHIR_BASE_URL", FHIR_BASE)
        self.mock_mode = _is_mock_mode()

    async def fetch_all(self, patient_id: str, encounter_id: str) -> dict:
        """Fetch all FHIR resources for a patient in parallel.

        Gracefully handles FHIR server unavailability by returning
        empty collections so the pipeline can still run with degraded
        data (e.g. using seed files or rule-based fallbacks).
        """
        # ── Mock Mode: load from seed files ──
        if self.mock_mode:
            print("[FHIR] Mock mode — loading from data/seed/ files")
            return self._load_mock_resources()

        # ── Live Mode: fetch from FHIR server ──
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                # Quick connectivity check
                try:
                    probe = await client.get(f"{self.base_url}/metadata", timeout=5)
                    if probe.status_code != 200:
                        raise httpx.ConnectError("FHIR metadata unreachable")
                except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout):
                    print(f"[FHIR] Server unavailable at {self.base_url} — falling back to seed data")
                    return self._load_mock_resources()

                tasks = {
                    "patient": client.get(f"{self.base_url}/Patient/{patient_id}"),
                    "encounter": client.get(f"{self.base_url}/Encounter/{encounter_id}"),
                    "conditions": client.get(f"{self.base_url}/Condition?subject=Patient/{patient_id}"),
                    "medications": client.get(f"{self.base_url}/MedicationRequest?subject=Patient/{patient_id}"),
                    "allergies": client.get(f"{self.base_url}/AllergyIntolerance?patient={patient_id}"),
                    "vitals": client.get(f"{self.base_url}/Observation?subject=Patient/{patient_id}&category=vital-signs&_sort=-date&_count=100"),
                    "labs": client.get(f"{self.base_url}/Observation?subject=Patient/{patient_id}&category=laboratory&_sort=-date&_count=100"),
                    "documents": client.get(f"{self.base_url}/DocumentReference?subject=Patient/{patient_id}"),
                    "diagnostic_reports": client.get(f"{self.base_url}/DiagnosticReport?subject=Patient/{patient_id}"),
                }

                results = {}
                responses = await asyncio.gather(*tasks.values(), return_exceptions=True)

                for key, resp in zip(tasks.keys(), responses):
                    if isinstance(resp, Exception):
                        results[key] = []
                    elif resp.status_code == 200:
                        data = resp.json()
                        if data.get("resourceType") == "Bundle":
                            results[key] = [e["resource"] for e in data.get("entry", [])]
                        else:
                            results[key] = data
                    else:
                        results[key] = []

                return results

        except (httpx.ConnectError, httpx.ConnectTimeout, OSError) as e:
            print(f"[FHIR] Connection failed: {e} — falling back to seed data")
            return self._load_mock_resources()

    def _load_mock_resources(self) -> dict:
        """Load all resources from data/seed/ JSON files."""
        resources = {
            "patient": _load_seed("patient.json"),
            "encounter": _load_seed("encounter.json"),
            "conditions": _load_seed("conditions.json"),
            "medications": _load_seed("medications.json"),
            "allergies": _load_seed("allergies.json"),
            "vitals": _load_seed("vitals.json"),
            "labs": _load_seed("labs.json"),
            "documents": _load_seed("documents.json"),
            "diagnostic_reports": [],
        }
        total = sum(len(v) if isinstance(v, list) else 1 for v in resources.values())
        print(f"[FHIR] Loaded {total} resources from seed files")
        return resources

    def _empty_resources(self) -> dict:
        """Return an empty resource set for graceful degradation."""
        return {
            "patient": {},
            "encounter": {},
            "conditions": [],
            "medications": [],
            "allergies": [],
            "vitals": [],
            "labs": [],
            "documents": [],
            "diagnostic_reports": [],
        }

    async def get_resource(self, resource_type: str, resource_id: str) -> dict:
        if self.mock_mode:
            return {"info": "Mock mode — resource not available individually"}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.base_url}/{resource_type}/{resource_id}")
                return resp.json()
        except (httpx.ConnectError, httpx.ConnectTimeout, OSError) as e:
            return {"error": f"FHIR server unavailable: {e}"}


