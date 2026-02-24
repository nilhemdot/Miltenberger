"""
Appointment store — in-memory scheduling for the doctor's office receptionist.

In production, replace this module with calls to your EHR/scheduling system
(e.g. Epic, Athena Health, Kareo, Jane App, etc.) via their APIs.

HIPAA note: This module stores patient data in memory only. For production
use, ensure all persistent storage is encrypted, access-controlled, and
compliant with HIPAA's technical safeguards.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from typing import Optional

# ---------------------------------------------------------------------------
# Data models (plain dicts to keep dependencies minimal)
# ---------------------------------------------------------------------------

# appointment = {
#   "id": str,
#   "patient_name": str,
#   "patient_dob": str,          # "MM/DD/YYYY"
#   "patient_phone": str,
#   "provider": str,             # doctor name
#   "appointment_type": str,     # "new patient" | "follow-up" | "sick visit" | etc.
#   "date": str,                 # "YYYY-MM-DD"
#   "time": str,                 # "HH:MM AM/PM"
#   "notes": str,
#   "status": str,               # "scheduled" | "cancelled" | "rescheduled"
#   "created_at": str,
# }

appointments: dict[str, dict] = {}

# ---------------------------------------------------------------------------
# Provider roster (customise in production via .env or database)
# ---------------------------------------------------------------------------

PROVIDERS: list[dict] = [
    {"name": "Dr. Smith", "specialty": "Family Medicine", "npi": "1234567890"},
    {"name": "Dr. Johnson", "specialty": "Internal Medicine", "npi": "0987654321"},
    {"name": "Dr. Patel", "specialty": "Pediatrics", "npi": "1122334455"},
]

PROVIDER_NAMES = [p["name"] for p in PROVIDERS]

# ---------------------------------------------------------------------------
# Available time slots (Mon–Fri, 8 AM – 4 PM, 30-min increments)
# Slots already taken by booked appointments are filtered out at lookup time.
# ---------------------------------------------------------------------------

SLOT_TIMES = [
    "8:00 AM", "8:30 AM", "9:00 AM", "9:30 AM",
    "10:00 AM", "10:30 AM", "11:00 AM", "11:30 AM",
    "1:00 PM", "1:30 PM", "2:00 PM", "2:30 PM",
    "3:00 PM", "3:30 PM", "4:00 PM",
]

APPOINTMENT_TYPES = [
    "New Patient",
    "Follow-Up",
    "Sick Visit / Urgent",
    "Annual Physical",
    "Lab Review",
    "Vaccination",
    "Telehealth",
]


def _booked_slots(date_str: str, provider: str) -> set[str]:
    """Return the set of times already booked for a given date + provider."""
    return {
        appt["time"]
        for appt in appointments.values()
        if appt["date"] == date_str
        and appt["provider"] == provider
        and appt["status"] == "scheduled"
    }


def _next_business_days(n: int = 7) -> list[str]:
    """Return the next n business days as YYYY-MM-DD strings."""
    days = []
    d = date.today() + timedelta(days=1)
    while len(days) < n:
        if d.weekday() < 5:  # Mon–Fri
            days.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return days


# ---------------------------------------------------------------------------
# Public scheduling functions
# ---------------------------------------------------------------------------


def get_available_slots(
    requested_date: Optional[str] = None,
    provider: Optional[str] = None,
) -> dict:
    """
    Return available appointment slots.

    If date or provider is omitted, returns next 3 available days for
    all providers (or the specified provider).
    """
    providers_to_check = [provider] if provider else PROVIDER_NAMES
    days_to_check = [requested_date] if requested_date else _next_business_days(5)

    availability: dict[str, list[dict]] = {}

    for day in days_to_check:
        day_slots = []
        for prov in providers_to_check:
            booked = _booked_slots(day, prov)
            free = [t for t in SLOT_TIMES if t not in booked]
            if free:
                day_slots.append({"provider": prov, "times": free[:6]})  # cap at 6 per provider
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
) -> dict:
    """Book a new appointment. Returns the appointment record or an error."""
    booked = _booked_slots(date_str, provider)
    if time_str in booked:
        return {"error": f"{time_str} on {date_str} is no longer available for {provider}. Please choose another slot."}

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
        "status": "scheduled",
        "created_at": datetime.utcnow().isoformat(),
    }
    appointments[appt_id] = record
    return {"success": True, "appointment": record}


def find_appointment(patient_name: str, patient_dob: str = "") -> list[dict]:
    """Find scheduled appointments by patient name (and optionally DOB)."""
    name_lower = patient_name.lower()
    matches = [
        appt for appt in appointments.values()
        if name_lower in appt["patient_name"].lower()
        and (not patient_dob or appt["patient_dob"] == patient_dob)
        and appt["status"] == "scheduled"
    ]
    return sorted(matches, key=lambda a: (a["date"], a["time"]))


def reschedule_appointment(
    appointment_id: str,
    new_date: str,
    new_time: str,
) -> dict:
    """Move an existing appointment to a new date/time."""
    appt = appointments.get(appointment_id)
    if not appt:
        return {"error": f"No appointment found with ID {appointment_id}."}
    if appt["status"] != "scheduled":
        return {"error": f"Appointment {appointment_id} is already {appt['status']}."}

    booked = _booked_slots(new_date, appt["provider"])
    if new_time in booked:
        return {"error": f"{new_time} on {new_date} is not available. Please choose another slot."}

    appt["date"] = new_date
    appt["time"] = new_time
    appt["status"] = "scheduled"
    appt["notes"] += f" | Rescheduled to {new_date} {new_time}"
    return {"success": True, "appointment": appt}


def cancel_appointment(appointment_id: str, reason: str = "") -> dict:
    """Cancel an appointment."""
    appt = appointments.get(appointment_id)
    if not appt:
        return {"error": f"No appointment found with ID {appointment_id}."}
    if appt["status"] == "cancelled":
        return {"error": "This appointment is already cancelled."}

    appt["status"] = "cancelled"
    appt["notes"] += f" | Cancelled: {reason}" if reason else " | Cancelled"
    return {"success": True, "appointment": appt}
