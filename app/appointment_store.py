"""
Appointment store — in-memory scheduling for the doctor's office receptionist.

In production, replace this module with calls to your EHR/scheduling system
(e.g. Epic, Athena Health, Kareo, Jane App) via their APIs.

HIPAA note: This module stores patient data in memory only. For production
use, ensure all persistent storage is encrypted, access-controlled, and
compliant with HIPAA's Technical Safeguards (45 CFR § 164.312).
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data store
# ---------------------------------------------------------------------------

appointments: dict[str, dict] = {}

# ---------------------------------------------------------------------------
# Provider roster — customise via PROVIDERS in .env or a database
# ---------------------------------------------------------------------------

PROVIDERS: list[dict] = [
    {"name": "Dr. Smith",   "specialty": "Family Medicine"},
    {"name": "Dr. Johnson", "specialty": "Internal Medicine"},
    {"name": "Dr. Patel",   "specialty": "Pediatrics"},
]

PROVIDER_NAMES = [p["name"] for p in PROVIDERS]

APPOINTMENT_TYPES = [
    "New Patient",
    "Follow-Up",
    "Sick Visit / Urgent",
    "Annual Physical",
    "Lab Review",
    "Vaccination",
    "Telehealth",
]

# Mon–Fri, 8 AM–4 PM, 30-min slots (lunch 12–1 excluded)
SLOT_TIMES = [
    "8:00 AM", "8:30 AM", "9:00 AM", "9:30 AM",
    "10:00 AM", "10:30 AM", "11:00 AM", "11:30 AM",
    "1:00 PM", "1:30 PM", "2:00 PM", "2:30 PM",
    "3:00 PM", "3:30 PM", "4:00 PM",
]


def _booked_slots(date_str: str, provider: str) -> set[str]:
    return {
        a["time"]
        for a in appointments.values()
        if a["date"] == date_str
        and a["provider"] == provider
        and a["status"] == "scheduled"
    }


def _next_business_days(n: int = 7) -> list[str]:
    days: list[str] = []
    d = date.today() + timedelta(days=1)
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return days


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_available_slots(
    requested_date: Optional[str] = None,
    provider: Optional[str] = None,
) -> dict:
    providers_to_check = [provider] if provider else PROVIDER_NAMES
    days_to_check = [requested_date] if requested_date else _next_business_days(5)

    availability: dict[str, list[dict]] = {}
    for day in days_to_check:
        day_slots = []
        for prov in providers_to_check:
            booked = _booked_slots(day, prov)
            free = [t for t in SLOT_TIMES if t not in booked]
            if free:
                day_slots.append({"provider": prov, "times": free[:6]})
        if day_slots:
            availability[day] = day_slots

    return {
        "available": availability,
        "providers": PROVIDER_NAMES,
        "appointment_types": APPOINTMENT_TYPES,
    }


def schedule_appointment(
    patient_name: str,
    patient_dob: str,
    patient_phone: str,
    provider: str,
    appointment_type: str,
    date_str: str,
    time_str: str,
    notes: str = "",
    is_new_patient: bool = False,
) -> dict:
    """Book a new appointment and fire confirmation SMS."""
    if time_str in _booked_slots(date_str, provider):
        return {
            "error": (
                f"{time_str} on {date_str} is no longer available for {provider}. "
                "Please choose another slot."
            )
        }

    appt_id = str(uuid.uuid4())[:8].upper()
    record = {
        "id": appt_id,
        "patient_name": patient_name,
        "patient_dob": patient_dob,
        "patient_phone": patient_phone,
        "provider": provider,
        "appointment_type": appointment_type,
        "date": date_str,
        "time": time_str,
        "notes": notes,
        "is_new_patient": is_new_patient,
        "status": "scheduled",
        "created_at": datetime.utcnow().isoformat(),
    }
    appointments[appt_id] = record

    # Fire confirmation SMS (import here to avoid circular imports)
    try:
        from app import sms  # noqa: PLC0415
        sms.send_appointment_confirmation(patient_phone, record)
        if is_new_patient:
            sms.send_intake_form_link(patient_phone, patient_name)
    except Exception as exc:
        logger.warning("SMS confirmation failed: %s", exc)

    return {"success": True, "appointment": record}


def find_appointment(patient_name: str, patient_dob: str = "") -> list[dict]:
    name_lower = patient_name.lower()
    matches = [
        a for a in appointments.values()
        if name_lower in a["patient_name"].lower()
        and (not patient_dob or a["patient_dob"] == patient_dob)
        and a["status"] == "scheduled"
    ]
    return sorted(matches, key=lambda a: (a["date"], a["time"]))


def reschedule_appointment(
    appointment_id: str,
    new_date: str,
    new_time: str,
) -> dict:
    """Reschedule and fire an SMS update."""
    appt = appointments.get(appointment_id)
    if not appt:
        return {"error": f"No appointment found with ID {appointment_id}."}
    if appt["status"] != "scheduled":
        return {"error": f"Appointment {appointment_id} is already {appt['status']}."}

    if new_time in _booked_slots(new_date, appt["provider"]):
        return {"error": f"{new_time} on {new_date} is not available. Please choose another slot."}

    appt["date"] = new_date
    appt["time"] = new_time
    appt["notes"] += f" | Rescheduled to {new_date} {new_time}"

    try:
        from app import sms  # noqa: PLC0415
        sms.send_appointment_rescheduled(appt["patient_phone"], appt)
    except Exception as exc:
        logger.warning("SMS reschedule notification failed: %s", exc)

    return {"success": True, "appointment": appt}


def cancel_appointment(appointment_id: str, reason: str = "") -> dict:
    """Cancel appointment, notify patient via SMS, and alert waitlist."""
    appt = appointments.get(appointment_id)
    if not appt:
        return {"error": f"No appointment found with ID {appointment_id}."}
    if appt["status"] == "cancelled":
        return {"error": "This appointment is already cancelled."}

    appt["status"] = "cancelled"
    appt["notes"] += f" | Cancelled: {reason}" if reason else " | Cancelled"

    # Notify patient
    try:
        from app import sms  # noqa: PLC0415
        sms.send_appointment_cancelled(appt["patient_phone"], appt)
    except Exception as exc:
        logger.warning("SMS cancellation notification failed: %s", exc)

    # Notify waitlisted patients about the newly opened slot
    try:
        from app import waitlist, sms  # noqa: PLC0415
        matches = waitlist.find_matches(appt["date"], appt["provider"])
        for entry in matches[:3]:  # Offer to up to 3 waitlisted patients
            sms.send_waitlist_offer(
                entry["patient_phone"],
                entry["patient_name"],
                appt["date"],
                appt["time"],
                appt["provider"],
            )
            waitlist.mark_offered(entry["id"])
            logger.info("Waitlist offer sent to %s", entry["patient_name"])
    except Exception as exc:
        logger.warning("Waitlist notification failed: %s", exc)

    return {"success": True, "appointment": appt}
