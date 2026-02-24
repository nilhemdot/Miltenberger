"""
SMS module — Twilio SMS for appointment confirmations, reminders,
intake form links, lab result notifications, and waitlist offers.

HIPAA note: SMS is not inherently encrypted. For PHI over SMS, obtain
patient consent and consider using a HIPAA-compliant messaging service.
"""

from __future__ import annotations

import logging

from twilio.rest import Client

from app.config import settings

logger = logging.getLogger(__name__)

INTAKE_FORM_URL = settings.intake_form_url  # Set in .env; e.g. your patient portal URL


def _client() -> Client:
    return Client(settings.twilio_account_sid, settings.twilio_auth_token)


def _send(to: str, body: str) -> bool:
    """Send an SMS. Returns True on success, False on failure."""
    if not to or not to.startswith("+"):
        logger.warning("Invalid phone number for SMS: %s", to)
        return False
    try:
        msg = _client().messages.create(
            to=to,
            from_=settings.twilio_phone_number,
            body=body,
        )
        logger.info("SMS sent to %s — SID %s", to, msg.sid)
        return True
    except Exception as exc:
        logger.error("SMS failed to %s: %s", to, exc)
        return False


# ---------------------------------------------------------------------------
# Appointment notifications
# ---------------------------------------------------------------------------


def send_appointment_confirmation(phone: str, appt: dict) -> bool:
    """Text the patient a booking confirmation."""
    body = (
        f"{settings.business_name}\n"
        f"Your appointment is confirmed!\n"
        f"  Patient: {appt['patient_name']}\n"
        f"  Provider: {appt['provider']}\n"
        f"  Date: {appt['date']}\n"
        f"  Time: {appt['time']}\n"
        f"  Type: {appt['appointment_type']}\n"
        f"  Confirmation #: {appt['id']}\n\n"
        f"Please arrive 15 min early with your insurance card and photo ID.\n"
        f"To cancel/reschedule call: {settings.twilio_phone_number}"
    )
    return _send(phone, body)


def send_appointment_reminder(phone: str, appt: dict) -> bool:
    """24-hour reminder SMS."""
    body = (
        f"Reminder from {settings.business_name}:\n"
        f"You have an appointment TOMORROW\n"
        f"  {appt['appointment_type']} with {appt['provider']}\n"
        f"  {appt['date']} at {appt['time']}\n\n"
        f"Reply CONFIRM to confirm or call {settings.twilio_phone_number} to reschedule.\n"
        f"Conf #: {appt['id']}"
    )
    return _send(phone, body)


def send_appointment_cancelled(phone: str, appt: dict) -> bool:
    """Notify patient their appointment was cancelled."""
    body = (
        f"{settings.business_name}\n"
        f"Your appointment on {appt['date']} at {appt['time']} "
        f"with {appt['provider']} has been cancelled.\n"
        f"Call {settings.twilio_phone_number} to reschedule."
    )
    return _send(phone, body)


def send_appointment_rescheduled(phone: str, appt: dict) -> bool:
    """Notify patient their appointment was rescheduled."""
    body = (
        f"{settings.business_name}\n"
        f"Your appointment has been rescheduled.\n"
        f"  Provider: {appt['provider']}\n"
        f"  New date: {appt['date']}\n"
        f"  New time: {appt['time']}\n"
        f"  Conf #: {appt['id']}\n\n"
        f"Call {settings.twilio_phone_number} if you need to make changes."
    )
    return _send(phone, body)


# ---------------------------------------------------------------------------
# New patient intake
# ---------------------------------------------------------------------------


def send_intake_form_link(phone: str, patient_name: str) -> bool:
    """Send a link to the new patient intake form."""
    if not INTAKE_FORM_URL:
        logger.info("INTAKE_FORM_URL not configured — skipping intake SMS")
        return False
    body = (
        f"Welcome to {settings.business_name}, {patient_name}!\n\n"
        f"Please complete your new patient intake forms before your appointment:\n"
        f"{INTAKE_FORM_URL}\n\n"
        f"Questions? Call us at {settings.twilio_phone_number}."
    )
    return _send(phone, body)


# ---------------------------------------------------------------------------
# Lab results
# ---------------------------------------------------------------------------


def send_lab_results_ready(phone: str, patient_name: str, provider: str) -> bool:
    """Notify a patient that their lab results are available."""
    portal_url = settings.patient_portal_url
    body = (
        f"{settings.business_name}\n"
        f"Hi {patient_name}, your lab results are now available.\n"
    )
    if portal_url:
        body += f"View them in your patient portal: {portal_url}\n"
    body += (
        f"If you have questions, call us at {settings.twilio_phone_number} "
        f"or ask to speak with {provider}'s office."
    )
    return _send(phone, body)


# ---------------------------------------------------------------------------
# Waitlist
# ---------------------------------------------------------------------------


def send_waitlist_offer(phone: str, patient_name: str, date_str: str, time_str: str, provider: str) -> bool:
    """Offer a newly opened slot to a waitlisted patient."""
    body = (
        f"{settings.business_name}\n"
        f"Good news, {patient_name}! An appointment has opened up:\n"
        f"  {provider}\n"
        f"  {date_str} at {time_str}\n\n"
        f"Call {settings.twilio_phone_number} now to claim this slot. "
        f"It will be offered to others if not claimed within 2 hours."
    )
    return _send(phone, body)


# ---------------------------------------------------------------------------
# Refill
# ---------------------------------------------------------------------------


def send_refill_approved(phone: str, patient_name: str, medication: str, pharmacy: str) -> bool:
    """Notify patient their refill was approved."""
    body = (
        f"{settings.business_name}\n"
        f"Hi {patient_name}, your refill for {medication} has been approved "
        f"and sent to {pharmacy}. Contact the pharmacy for pick-up details.\n"
        f"Questions? Call {settings.twilio_phone_number}."
    )
    return _send(phone, body)


# ---------------------------------------------------------------------------
# Post-visit follow-up
# ---------------------------------------------------------------------------


def send_followup_message(phone: str, patient_name: str, provider: str) -> bool:
    """Post-visit check-in message."""
    body = (
        f"{settings.business_name}\n"
        f"Hi {patient_name}, we hope your visit with {provider} went well!\n"
        f"If you have any questions or concerns, please call us at "
        f"{settings.twilio_phone_number}.\n"
        f"You can also request a follow-up appointment when you call."
    )
    return _send(phone, body)
