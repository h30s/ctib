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
        """Fetch all FHIR resources for a patient in parallel.

        Gracefully handles FHIR server unavailability by returning
        empty collections so the pipeline can still run with degraded
        data (e.g. using seed files or rule-based fallbacks).
        """
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                # Quick connectivity check
                try:
                    probe = await client.get(f"{self.base_url}/metadata", timeout=5)
                    if probe.status_code != 200:
                        raise httpx.ConnectError("FHIR metadata unreachable")
                except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout):
                    print(f"[FHIR] Server unavailable at {self.base_url} — using empty resource set")
                    return self._empty_resources()

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
            print(f"[FHIR] Connection failed: {e} — using empty resource set")
            return self._empty_resources()

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
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.base_url}/{resource_type}/{resource_id}")
                return resp.json()
        except (httpx.ConnectError, httpx.ConnectTimeout, OSError) as e:
            return {"error": f"FHIR server unavailable: {e}"}


