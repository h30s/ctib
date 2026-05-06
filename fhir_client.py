"""Async FHIR client for parallel resource fetching."""
import os
import asyncio
import httpx

FHIR_BASE = os.getenv("FHIR_BASE_URL", "http://localhost:8080/fhir")


class FHIRClient:
    """Async FHIR client that fetches all resources for a patient in parallel."""

    def __init__(self, base_url: str = None):
        self.base_url = base_url or os.getenv("FHIR_BASE_URL", FHIR_BASE)

    async def fetch_all(self, patient_id: str, encounter_id: str) -> dict:
        """Fetch all FHIR resources for a patient in parallel."""
        async with httpx.AsyncClient(timeout=30) as client:
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
                    results[key] = {"error": str(resp)}
                elif resp.status_code == 200:
                    data = resp.json()
                    if data.get("resourceType") == "Bundle":
                        results[key] = [e["resource"] for e in data.get("entry", [])]
                    else:
                        results[key] = data
                else:
                    results[key] = {"error": f"HTTP {resp.status_code}"}

            return results

    async def get_resource(self, resource_type: str, resource_id: str) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{self.base_url}/{resource_type}/{resource_id}")
            return resp.json()

