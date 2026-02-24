"""
Insurance information store.

Collects and stores patient insurance details during scheduling.
In production, connect to a clearinghouse API (e.g. Availity, Change Healthcare)
for real-time eligibility verification.
"""

from __future__ import annotations

from datetime import datetime

# insurance_record = {
#   "patient_name": str,
#   "patient_dob": str,
#   "primary_insurance": {
#       "provider_name": str,      # e.g. "Blue Cross Blue Shield"
#       "member_id": str,
#       "group_number": str,
#       "policy_holder_name": str,
#       "policy_holder_dob": str,  # if different from patient
#       "plan_name": str,          # e.g. "PPO", "HMO"
#   },
#   "secondary_insurance": { ... } | None,
#   "verified": bool,
#   "verified_at": str | None,
#   "updated_at": str,
# }

_insurance_store: dict[str, dict] = {}  # key: "{patient_name}|{dob}"


def _key(patient_name: str, patient_dob: str) -> str:
    return f"{patient_name.lower().strip()}|{patient_dob.strip()}"


def save_insurance(
    patient_name: str,
    patient_dob: str,
    primary_provider: str,
    member_id: str,
    group_number: str = "",
    policy_holder_name: str = "",
    policy_holder_dob: str = "",
    plan_name: str = "",
    secondary_provider: str = "",
    secondary_member_id: str = "",
) -> dict:
    """Save or update insurance information for a patient."""
    k = _key(patient_name, patient_dob)
    record = {
        "patient_name": patient_name,
        "patient_dob": patient_dob,
        "primary_insurance": {
            "provider_name": primary_provider,
            "member_id": member_id,
            "group_number": group_number,
            "policy_holder_name": policy_holder_name or patient_name,
            "policy_holder_dob": policy_holder_dob or patient_dob,
            "plan_name": plan_name,
        },
        "secondary_insurance": {
            "provider_name": secondary_provider,
            "member_id": secondary_member_id,
        } if secondary_provider else None,
        "verified": False,
        "verified_at": None,
        "updated_at": datetime.utcnow().isoformat(),
    }
    _insurance_store[k] = record
    return record


def get_insurance(patient_name: str, patient_dob: str) -> dict | None:
    return _insurance_store.get(_key(patient_name, patient_dob))


def mark_verified(patient_name: str, patient_dob: str) -> bool:
    record = _insurance_store.get(_key(patient_name, patient_dob))
    if record:
        record["verified"] = True
        record["verified_at"] = datetime.utcnow().isoformat()
        return True
    return False


def get_all_unverified() -> list[dict]:
    return [r for r in _insurance_store.values() if not r["verified"]]
