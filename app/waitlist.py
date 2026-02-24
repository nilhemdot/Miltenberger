"""
Waitlist management — patients are added when no slots are available
and notified via SMS when a cancellation opens a matching slot.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional


# waitlist_entry = {
#   "id": str,
#   "patient_name": str,
#   "patient_dob": str,
#   "patient_phone": str,
#   "provider": str | None,     # preferred provider, or None for any
#   "appointment_type": str,
#   "preferred_dates": list[str],  # YYYY-MM-DD, empty = any date
#   "notes": str,
#   "status": "waiting" | "offered" | "booked" | "removed",
#   "added_at": str,
#   "offered_at": str | None,
# }

waitlist: list[dict] = []


def add_to_waitlist(
    patient_name: str,
    patient_dob: str,
    patient_phone: str,
    appointment_type: str,
    provider: Optional[str] = None,
    preferred_dates: Optional[list[str]] = None,
    notes: str = "",
) -> dict:
    """Add a patient to the waitlist."""
    entry = {
        "id": str(uuid.uuid4())[:8].upper(),
        "patient_name": patient_name,
        "patient_dob": patient_dob,
        "patient_phone": patient_phone,
        "provider": provider,
        "appointment_type": appointment_type,
        "preferred_dates": preferred_dates or [],
        "notes": notes,
        "status": "waiting",
        "added_at": datetime.utcnow().isoformat(),
        "offered_at": None,
    }
    waitlist.append(entry)
    return entry


def get_waitlist(status: str = "waiting") -> list[dict]:
    return [e for e in waitlist if e["status"] == status]


def find_matches(date_str: str, provider: str) -> list[dict]:
    """
    Find waitlisted patients who could take a newly opened slot.
    Matches on provider (or any-provider) and date preference (or any date).
    """
    matches = []
    for entry in waitlist:
        if entry["status"] != "waiting":
            continue
        provider_match = entry["provider"] is None or entry["provider"] == provider
        date_match = not entry["preferred_dates"] or date_str in entry["preferred_dates"]
        if provider_match and date_match:
            matches.append(entry)
    return matches


def mark_offered(waitlist_id: str) -> None:
    for entry in waitlist:
        if entry["id"] == waitlist_id:
            entry["status"] = "offered"
            entry["offered_at"] = datetime.utcnow().isoformat()
            break


def mark_booked(waitlist_id: str) -> None:
    for entry in waitlist:
        if entry["id"] == waitlist_id:
            entry["status"] = "booked"
            break


def remove_from_waitlist(waitlist_id: str) -> bool:
    for entry in waitlist:
        if entry["id"] == waitlist_id:
            entry["status"] = "removed"
            return True
    return False
