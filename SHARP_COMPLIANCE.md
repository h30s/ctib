# SHARP Extension Spec Compliance — CTIB

> **SHARP** (Secure Healthcare Agent Runtime Protocol) is Prompt Opinion's extension specification for propagating healthcare context — patient identity, consent, FHIR tokens, and access scope — across agent boundaries in multi-agent workflows.

## How CTIB Implements SHARP

CTIB implements SHARP context propagation at every stage of the pipeline. The SHARP token is the **single source of truth** for patient context and is never passed directly to any MCP tool — only an escrow reference is shared.

### SHARP Context Token Fields

| SHARP Field | CTIB Implementation | File |
|---|---|---|
| `sharp_version` | `"1.0"` — hardcoded to current spec | `schemas/sharp_context.py` |
| `session_id` | UUID auto-generated per session — used as escrow key | `schemas/sharp_context.py` |
| `fhir_base_url` | Configurable via `FHIR_BASE_URL` env var | `schemas/sharp_context.py` |
| `patient_id` | FHIR Patient resource ID (e.g. `pt-maria-chen-001`) | `schemas/sharp_context.py` |
| `encounter_id` | FHIR Encounter resource ID (e.g. `enc-icu-day5`) | `schemas/sharp_context.py` |
| `purpose_of_use` | `"CARE_TRANSITION"` — coded use case | `schemas/sharp_context.py` |
| `requesting_clinician` | FHIR Practitioner resource reference | `schemas/sharp_context.py` |
| `context_scope` | SMART-on-FHIR style scope list (7 read scopes) | `schemas/sharp_context.py` |
| `consent_reference` | FHIR Consent resource reference | `schemas/sharp_context.py` |
| `token_expiry` | ISO 8601 timestamp, default 4h TTL | `schemas/sharp_context.py` |

### SHARP Propagation Flow

```
1. API Request (POST /api/run-ctib)
   └── SHARP token minted with patient_id + encounter_id

2. ContextBrokerAgent.register_sharp_context()
   └── Token stored in escrow — session_id returned
   └── FHIR AuditEvent: REGISTER

3. ContextBrokerAgent.authorize_signal_exchange()
   └── Scope check: required scopes ⊆ token scopes
   └── FHIR AuditEvent: AUTHORIZE or DENY

4. MCP Swarm Execution
   └── Tools receive "escrow-ref" — NEVER the patient ID directly
   └── FHIR data fetched via escrow-authorized FHIRClient

5. ContextBrokerAgent.deposit_signal()
   └── Each signal envelope deposited under session escrow
   └── FHIR AuditEvent: DEPOSIT_SIGNAL

6. ContextBrokerAgent.assemble_epistemic_bundle()
   └── Bundle references Patient/ and Encounter/ via SHARP token
   └── sharp_session_id embedded in bundle for traceability
   └── FHIR AuditEvent: ASSEMBLE_BUNDLE

7. TransitionDeliveryAgent.deliver()
   └── Scoped SHARPDeliveryToken minted for receiving agent
   └── Delivery token limits which bundle sections are visible
   └── FHIR AuditEvent: AUTHORIZE_DELIVERY
```

### SHARP Delivery Token (Sub-Token)

When delivering a bundle to a receiving agent, CTIB mints a **scoped sub-token** that restricts what the receiver can see:

| Field | Description |
|---|---|
| `parent_session_id` | Links back to original SHARP session |
| `delivery_token_id` | Unique delivery token ID |
| `receiving_agent_id` | Identity of the receiving agent |
| `permitted_sections` | Which bundle sections the receiver may access |
| `expiry` | Optional TTL for the delivery token |

### Privacy Guarantees

1. **ContextBrokerAgent uses ZERO LLM inference** — the privacy spine is entirely deterministic
2. **Patient ID never leaves escrow** — MCP tools see `"escrow-ref"`, not `pt-maria-chen-001`
3. **Scope-based authorization** — each agent must declare required scopes; denied if not subset of token
4. **Full FHIR AuditEvent trail** — every context access, deposit, assembly, and delivery is audited
5. **Scoped delivery** — receiving agents get a restricted sub-token, not the full session token

### FHIR AuditEvent Types Generated

| Action | Agent | Description |
|---|---|---|
| `CTIB-REGISTER` | ContextBrokerAgent | SHARP token registered in escrow |
| `CTIB-AUTHORIZE` | Any agent | Signal exchange authorized |
| `CTIB-DENY` | Any agent | Signal exchange denied (scope mismatch) |
| `CTIB-DEPOSIT_SIGNAL` | MCP Servers | Signal envelope deposited |
| `CTIB-DEPOSIT_DISSONANCE` | Dissonance-MCP | Dissonance registry deposited |
| `CTIB-ASSEMBLE_BUNDLE` | ContextBrokerAgent | Bundle assembled from escrow |
| `CTIB-AUTHORIZE_DELIVERY` | ContextBrokerAgent | Delivery sub-token minted |
| `CTIB-DELIVERED` | TransitionDeliveryAgent | Bundle delivered via A2A |
