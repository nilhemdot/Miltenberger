"""
After-hours detection and routing.

Checks whether the current time falls within configured business hours
and provides appropriate TwiML/messages for after-hours callers.
"""

from __future__ import annotations

from datetime import datetime, time
import zoneinfo

from twilio.twiml.voice_response import VoiceResponse

from app.config import settings

# Business hours: Mon=0 … Fri=4, Sat=5, Sun=6
# Configurable via OFFICE_OPEN_TIME / OFFICE_CLOSE_TIME in .env (24h HH:MM)
_OPEN = time(*[int(x) for x in settings.office_open_time.split(":")])
_CLOSE = time(*[int(x) for x in settings.office_close_time.split(":")])
_TZ = zoneinfo.ZoneInfo(settings.office_timezone)


def is_business_hours() -> bool:
    """Return True if the current time is within business hours (Mon–Fri)."""
    now = datetime.now(_TZ)
    if now.weekday() >= 5:  # Saturday or Sunday
        return False
    return _OPEN <= now.time() < _CLOSE


def after_hours_twiml() -> str:
    """
    TwiML to play when a call arrives outside business hours.
    - If AFTER_HOURS_NUMBER is configured, transfer the call there.
    - Otherwise, play a message and offer voicemail.
    """
    response = VoiceResponse()
    open_str = datetime.now(_TZ).replace(
        hour=_OPEN.hour, minute=_OPEN.minute
    ).strftime("%-I:%M %p")
    close_str = datetime.now(_TZ).replace(
        hour=_CLOSE.hour, minute=_CLOSE.minute
    ).strftime("%-I:%M %p")

    if settings.after_hours_number:
        response.say(
            f"Thank you for calling {settings.business_name}. "
            f"Our office is currently closed. "
            f"Our hours are {settings.business_hours}. "
            f"I'm transferring you to our after-hours service now.",
            voice="Polly.Joanna",
        )
        response.dial(settings.after_hours_number)
    else:
        response.say(
            f"Thank you for calling {settings.business_name}. "
            f"Our office is currently closed. "
            f"Our hours are {settings.business_hours}. "
            f"If this is a medical emergency, please hang up and call 9-1-1. "
            f"Otherwise, please leave a message and we will return your call "
            f"during business hours.",
            voice="Polly.Joanna",
        )
        response.record(
            max_length=120,
            action=f"{settings.server_base_url}/twilio/voicemail",
            method="POST",
            finish_on_key="#",
            play_beep=True,
        )

    return str(response)
