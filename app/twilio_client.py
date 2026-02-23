"""Twilio client for managing call transfers and conference rooms."""

from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Dial
from app.config import settings

# Module-level call state (for single-instance deployments)
# For production, use Redis or a database.
_active_calls: dict[str, str] = {}  # vapi_call_id -> twilio_call_sid


def get_twilio_client() -> Client:
    return Client(settings.twilio_account_sid, settings.twilio_auth_token)


def register_call(vapi_call_id: str, twilio_call_sid: str) -> None:
    """Map a Vapi call ID to a Twilio CallSid."""
    _active_calls[vapi_call_id] = twilio_call_sid


def transfer_call_to_agent(twilio_call_sid: str, reason: str = "") -> dict:
    """
    Transfer a Twilio call to the human agent number via conference.

    Both the caller (currently talking to the AI) and the agent are
    connected into a shared Twilio conference room.
    """
    client = get_twilio_client()
    conference_name = f"transfer_{twilio_call_sid}"
    base_url = settings.server_base_url

    # Redirect the caller's leg into the conference room
    client.calls(twilio_call_sid).update(
        url=f"{base_url}/twilio/conference?name={conference_name}",
        method="POST",
    )

    # Dial the human agent into the same conference room
    agent_call = client.calls.create(
        to=settings.human_agent_number,
        from_=settings.twilio_phone_number,
        url=f"{base_url}/twilio/conference?name={conference_name}",
        method="POST",
        status_callback=f"{base_url}/twilio/agent-status?conference={conference_name}&caller_sid={twilio_call_sid}",
        status_callback_method="POST",
        status_callback_event=["completed", "no-answer", "busy", "failed"],
    )

    return {"conference": conference_name, "agent_call_sid": agent_call.sid}


def conference_twiml(conference_name: str) -> str:
    """Generate TwiML to join a named conference room."""
    response = VoiceResponse()
    dial = Dial()
    dial.conference(
        conference_name,
        start_conference_on_enter=True,
        end_conference_on_exit=True,
        wait_url="http://twimlets.com/holdmusic?Bucket=com.twilio.music.classical",
    )
    response.append(dial)
    return str(response)


def agent_unavailable_twiml() -> str:
    """TwiML played when the human agent does not answer."""
    response = VoiceResponse()
    response.say(
        "I'm sorry, all of our agents are currently unavailable. "
        "Please leave a message after the tone and we will call you back.",
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


def make_outbound_call(to_number: str, twiml_url: str) -> str:
    """Initiate an outbound Twilio call."""
    client = get_twilio_client()
    call = client.calls.create(
        to=to_number,
        from_=settings.twilio_phone_number,
        url=twiml_url,
        method="POST",
    )
    return call.sid
