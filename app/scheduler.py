"""
APScheduler jobs for automated outbound tasks:

  - Daily 8 AM: send SMS reminders for tomorrow's appointments
  - Daily 8 AM: trigger AI reminder calls for tomorrow's appointments
  - Daily 9 AM: trigger post-visit follow-up SMS for yesterday's visits
  - Daily 8 AM: expire stale "offered" waitlist entries back to "waiting"
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app import appointment_store, sms, waitlist
from app.config import settings

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


# ---------------------------------------------------------------------------
# Job functions
# ---------------------------------------------------------------------------


async def _send_sms_reminders() -> None:
    """Send SMS reminders for all appointments scheduled for tomorrow."""
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    count = 0
    for appt in appointment_store.appointments.values():
        if appt["date"] == tomorrow and appt["status"] == "scheduled":
            phone = appt.get("patient_phone", "")
            if phone:
                sms.send_appointment_reminder(phone, appt)
                count += 1
    logger.info("SMS reminders sent for %d appointments on %s", count, tomorrow)


async def _send_reminder_calls() -> None:
    """
    Trigger Vapi outbound reminder calls for tomorrow's appointments.
    Uses a dedicated reminder assistant if VAPI_REMINDER_ASSISTANT_ID is set,
    otherwise falls back to the main assistant.
    """
    # Import here to avoid circular imports at module load
    from app import vapi_client  # noqa: PLC0415

    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    assistant_id = settings.vapi_reminder_assistant_id or settings.vapi_assistant_id

    for appt in appointment_store.appointments.values():
        if appt["date"] == tomorrow and appt["status"] == "scheduled":
            phone = appt.get("patient_phone", "")
            if phone and assistant_id:
                try:
                    vapi_client.create_outbound_call(phone, assistant_id=assistant_id)
                    logger.info("Reminder call initiated to %s for appt %s", phone, appt["id"])
                except Exception as exc:
                    logger.error("Reminder call failed for %s: %s", appt["id"], exc)


async def _send_followup_sms() -> None:
    """Send post-visit follow-up SMS for appointments that occurred yesterday."""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    count = 0
    for appt in appointment_store.appointments.values():
        if appt["date"] == yesterday and appt["status"] == "scheduled":
            phone = appt.get("patient_phone", "")
            if phone:
                sms.send_followup_message(phone, appt["patient_name"], appt["provider"])
                count += 1
    logger.info("Follow-up SMS sent for %d visits on %s", count, yesterday)


async def _reset_stale_waitlist_offers() -> None:
    """Re-open waitlist entries that were offered but not booked within 2 hours."""
    from datetime import datetime, timezone  # noqa: PLC0415
    now = datetime.now(timezone.utc)
    for entry in waitlist.waitlist:
        if entry["status"] == "offered" and entry.get("offered_at"):
            offered_dt = datetime.fromisoformat(entry["offered_at"]).replace(tzinfo=timezone.utc)
            hours_elapsed = (now - offered_dt).total_seconds() / 3600
            if hours_elapsed >= 2:
                entry["status"] = "waiting"
                entry["offered_at"] = None
                logger.info("Waitlist entry %s reset to waiting (offer expired)", entry["id"])


# ---------------------------------------------------------------------------
# Scheduler lifecycle
# ---------------------------------------------------------------------------


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()

        tz = settings.office_timezone

        _scheduler.add_job(
            _send_sms_reminders,
            CronTrigger(hour=8, minute=0, timezone=tz),
            id="sms_reminders",
            replace_existing=True,
        )
        _scheduler.add_job(
            _send_reminder_calls,
            CronTrigger(hour=8, minute=15, timezone=tz),
            id="reminder_calls",
            replace_existing=True,
        )
        _scheduler.add_job(
            _send_followup_sms,
            CronTrigger(hour=9, minute=0, timezone=tz),
            id="followup_sms",
            replace_existing=True,
        )
        _scheduler.add_job(
            _reset_stale_waitlist_offers,
            CronTrigger(minute="*/30", timezone=tz),  # every 30 min
            id="reset_waitlist_offers",
            replace_existing=True,
        )

    return _scheduler
