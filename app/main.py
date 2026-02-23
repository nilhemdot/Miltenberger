"""
AI Receptionist — FastAPI server

Handles webhooks from both Vapi (assistant events & tool calls)
and Twilio (call status, conference, voicemail).
"""

import json
import logging
from datetime import datetime

from fastapi import FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from app import twilio_client, vapi_client
from app.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="AI Receptionist", version="1.0.0")

# In-memory message log (use a database in production)
messages_log: list[dict] = []


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    return {"status": "ok", "business": settings.business_name}


# ---------------------------------------------------------------------------
# Vapi webhooks — assistant lifecycle events
# ---------------------------------------------------------------------------


@app.post("/vapi/webhook")
async def vapi_webhook(request: Request):
    """
    Receives server-side events from Vapi for the AI assistant.

    Event types handled:
      - call-started      : register Twilio CallSid
      - call-ended        : log call summary
      - tool-calls        : handled via dedicated /vapi/tool/* routes
      - transcript        : optional real-time transcript logging
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    event_type = body.get("message", {}).get("type", "")
    logger.info("Vapi event: %s", event_type)

    if event_type == "call-started":
        call = body["message"].get("call", {})
        vapi_call_id = call.get("id", "")
        twilio_sid = call.get("phoneCallProviderDetails", {}).get("callSid", "")
        if vapi_call_id and twilio_sid:
            twilio_client.register_call(vapi_call_id, twilio_sid)
            logger.info("Call started — Vapi: %s | Twilio: %s", vapi_call_id, twilio_sid)

    elif event_type == "call-ended":
        call = body["message"].get("call", {})
        logger.info(
            "Call ended — id=%s duration=%ss",
            call.get("id"),
            call.get("endedAt", ""),
        )

    elif event_type == "transcript":
        role = body["message"].get("role", "")
        transcript = body["message"].get("transcript", "")
        logger.info("Transcript [%s]: %s", role, transcript)

    return JSONResponse({"received": True})


# ---------------------------------------------------------------------------
# Vapi tool call handlers
# ---------------------------------------------------------------------------


@app.post("/vapi/tool/transfer")
async def tool_transfer(request: Request):
    """
    Called by Vapi when the assistant invokes `transfer_to_agent`.
    Redirects the caller's Twilio leg into a conference and dials the agent.
    """
    body = await request.json()
    tool_call = body.get("message", {}).get("toolCall", {})
    args = tool_call.get("function", {}).get("arguments", {})
    if isinstance(args, str):
        args = json.loads(args)

    reason = args.get("reason", "Caller requested a human agent")

    call = body.get("message", {}).get("call", {})
    twilio_sid = call.get("phoneCallProviderDetails", {}).get("callSid", "")

    if not twilio_sid:
        logger.error("No Twilio CallSid available for transfer")
        return JSONResponse(
            {
                "results": [
                    {
                        "toolCallId": tool_call.get("id", ""),
                        "result": (
                            "I'm sorry, I wasn't able to transfer your call right now. "
                            "Would you like to leave a message instead?"
                        ),
                    }
                ]
            }
        )

    if not settings.human_agent_number:
        return JSONResponse(
            {
                "results": [
                    {
                        "toolCallId": tool_call.get("id", ""),
                        "result": (
                            "I'm sorry, no agents are available right now. "
                            "Would you like to leave a message?"
                        ),
                    }
                ]
            }
        )

    logger.info("Transferring call %s — reason: %s", twilio_sid, reason)
    transfer_result = twilio_client.transfer_call_to_agent(twilio_sid, reason)

    return JSONResponse(
        {
            "results": [
                {
                    "toolCallId": tool_call.get("id", ""),
                    "result": (
                        "I'm connecting you with a human agent now. "
                        "Please hold for a moment."
                    ),
                }
            ]
        }
    )


@app.post("/vapi/tool/message")
async def tool_message(request: Request):
    """
    Called by Vapi when the assistant invokes `take_message`.
    Stores the message and confirms to the caller.
    """
    body = await request.json()
    tool_call = body.get("message", {}).get("toolCall", {})
    args = tool_call.get("function", {}).get("arguments", {})
    if isinstance(args, str):
        args = json.loads(args)

    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "caller_name": args.get("caller_name", "Unknown"),
        "caller_phone": args.get("caller_phone", "Not provided"),
        "message": args.get("message", ""),
    }
    messages_log.append(entry)
    logger.info("Message taken: %s", entry)

    return JSONResponse(
        {
            "results": [
                {
                    "toolCallId": tool_call.get("id", ""),
                    "result": (
                        f"I've recorded your message, {entry['caller_name']}. "
                        "Someone from our team will get back to you soon."
                    ),
                }
            ]
        }
    )


# ---------------------------------------------------------------------------
# Twilio webhooks — conference & voicemail
# ---------------------------------------------------------------------------


@app.post("/twilio/conference")
async def twilio_conference(request: Request, name: str = ""):
    """Returns TwiML to place the caller into a named conference room."""
    conference_name = name or "default_conference"
    twiml = twilio_client.conference_twiml(conference_name)
    return Response(content=twiml, media_type="text/xml")


@app.post("/twilio/agent-status")
async def twilio_agent_status(
    request: Request,
    conference: str = "",
    caller_sid: str = "",
    CallStatus: str = Form(default=""),
):
    """
    Status callback when the human agent leg completes.
    If the agent is unavailable, redirect the caller to voicemail.
    """
    logger.info("Agent status: %s (conference=%s)", CallStatus, conference)

    if CallStatus in ("no-answer", "busy", "failed", "canceled"):
        logger.info("Agent unavailable (%s) — redirecting caller to voicemail", CallStatus)
        if caller_sid:
            try:
                client = twilio_client.get_twilio_client()
                client.calls(caller_sid).update(
                    url=f"{settings.server_base_url}/twilio/unavailable",
                    method="POST",
                )
            except Exception as exc:
                logger.error("Failed to redirect caller: %s", exc)

    return PlainTextResponse("OK")


@app.post("/twilio/unavailable")
async def twilio_unavailable():
    """TwiML played when no human agent is available."""
    twiml = twilio_client.agent_unavailable_twiml()
    return Response(content=twiml, media_type="text/xml")


@app.post("/twilio/voicemail")
async def twilio_voicemail(
    RecordingUrl: str = Form(default=""),
    RecordingSid: str = Form(default=""),
    From: str = Form(default=""),
):
    """Receives voicemail recording details after the caller leaves a message."""
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "caller_number": From,
        "recording_url": RecordingUrl,
        "recording_sid": RecordingSid,
        "type": "voicemail",
    }
    messages_log.append(entry)
    logger.info("Voicemail received: %s", entry)

    from twilio.twiml.voice_response import VoiceResponse
    response = VoiceResponse()
    response.say(
        "Thank you for your message. We will call you back as soon as possible. Goodbye.",
        voice="Polly.Joanna",
    )
    response.hangup()
    return Response(content=str(response), media_type="text/xml")


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@app.get("/admin/messages")
async def admin_messages():
    """View all recorded messages and voicemails."""
    return JSONResponse(messages_log)


@app.post("/admin/call")
async def admin_outbound_call(request: Request):
    """
    Initiate an outbound call via the AI receptionist.

    Body: {"to": "+1XXXXXXXXXX"}
    """
    body = await request.json()
    to_number = body.get("to")
    if not to_number:
        raise HTTPException(status_code=400, detail="'to' phone number is required")

    result = vapi_client.create_outbound_call(to_number)
    return JSONResponse(result)


@app.get("/admin/calls")
async def admin_list_calls(limit: int = 20):
    """List recent calls from Vapi."""
    calls = vapi_client.list_calls(limit=limit)
    return JSONResponse(calls)
