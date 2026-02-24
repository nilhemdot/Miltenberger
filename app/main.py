"""
Doctor's Office AI Receptionist — FastAPI server

Handles webhooks from Vapi (assistant events & tool calls) and
Twilio (call routing, conference, voicemail).

HIPAA note: This server logs call data to memory only. For production,
ensure all storage is encrypted at rest, access-controlled, and
compliant with HIPAA's technical safeguards (45 CFR § 164.312).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from fastapi import FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from app import appointment_store, twilio_client, vapi_client
from app.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Doctor's Office AI Receptionist", version="2.0.0")

# In-memory logs — replace with encrypted DB in production
messages_log: list[dict] = []
refill_requests: list[dict] = []
call_log: list[dict] = []


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _parse_tool_call(body: dict) -> tuple[dict, dict]:
    """Extract tool_call and function arguments from a Vapi webhook body."""
    tool_call = body.get("message", {}).get("toolCall", {})
    args = tool_call.get("function", {}).get("arguments", {})
    if isinstance(args, str):
        args = json.loads(args)
    return tool_call, args


def _tool_response(tool_call: dict, result: str) -> JSONResponse:
    return JSONResponse(
        {"results": [{"toolCallId": tool_call.get("id", ""), "result": result}]}
    )


def _twilio_sid(body: dict) -> str:
    return body.get("message", {}).get("call", {}).get(
        "phoneCallProviderDetails", {}
    ).get("callSid", "")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "practice": settings.business_name,
        "appointments_today": sum(
            1 for a in appointment_store.appointments.values()
            if a["date"] == datetime.utcnow().date().isoformat()
            and a["status"] == "scheduled"
        ),
    }


# ---------------------------------------------------------------------------
# Vapi lifecycle webhook
# ---------------------------------------------------------------------------


@app.post("/vapi/webhook")
async def vapi_webhook(request: Request):
    """Receives server-side events from the Vapi assistant."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    msg = body.get("message", {})
    event_type = msg.get("type", "")
    logger.info("Vapi event: %s", event_type)

    if event_type == "call-started":
        call = msg.get("call", {})
        vapi_call_id = call.get("id", "")
        twilio_sid = call.get("phoneCallProviderDetails", {}).get("callSid", "")
        if vapi_call_id and twilio_sid:
            twilio_client.register_call(vapi_call_id, twilio_sid)
        call_log.append({
            "type": "call-started",
            "vapi_call_id": vapi_call_id,
            "twilio_sid": twilio_sid,
            "started_at": datetime.utcnow().isoformat(),
        })

    elif event_type == "call-ended":
        call = msg.get("call", {})
        logger.info("Call ended — id=%s", call.get("id"))
        call_log.append({
            "type": "call-ended",
            "vapi_call_id": call.get("id"),
            "ended_at": datetime.utcnow().isoformat(),
        })

    return JSONResponse({"received": True})


# ---------------------------------------------------------------------------
# Tool: check_availability
# ---------------------------------------------------------------------------


@app.post("/vapi/tool/availability")
async def tool_availability(request: Request):
    body = await request.json()
    tool_call, args = _parse_tool_call(body)

    result = appointment_store.get_available_slots(
        requested_date=args.get("preferred_date"),
        provider=args.get("preferred_provider"),
    )

    available = result["available"]
    if not available:
        text = "I'm sorry, there are no available slots in the next 5 business days. Let me take a message for our scheduling team."
    else:
        lines = []
        for day, providers in list(available.items())[:3]:
            for prov_info in providers:
                times_str = ", ".join(prov_info["times"][:4])
                lines.append(f"{day} with {prov_info['provider']}: {times_str}")
        text = "Here are our available appointments:\n" + "\n".join(lines)
        text += f"\n\nWe offer: {', '.join(result['appointment_types'][:4])}, and more."

    return _tool_response(tool_call, text)


# ---------------------------------------------------------------------------
# Tool: schedule_appointment
# ---------------------------------------------------------------------------


@app.post("/vapi/tool/schedule")
async def tool_schedule(request: Request):
    body = await request.json()
    tool_call, args = _parse_tool_call(body)

    result = appointment_store.schedule_appointment(
        patient_name=args["patient_name"],
        patient_dob=args["patient_dob"],
        patient_phone=args["patient_phone"],
        provider=args["provider"],
        appointment_type=args["appointment_type"],
        date_str=args["date"],
        time_str=args["time"],
        notes=args.get("notes", ""),
    )

    if "error" in result:
        return _tool_response(tool_call, result["error"])

    appt = result["appointment"]
    text = (
        f"Your appointment is confirmed! Here are the details: "
        f"{appt['appointment_type']} with {appt['provider']} on "
        f"{appt['date']} at {appt['time']}. "
        f"Your confirmation number is {appt['id']}. "
        f"Please arrive 15 minutes early and bring your insurance card and a photo ID. "
        f"To cancel or reschedule, please call us at least 24 hours in advance."
    )
    logger.info("Appointment scheduled: %s", appt)
    return _tool_response(tool_call, text)


# ---------------------------------------------------------------------------
# Tool: find_appointment
# ---------------------------------------------------------------------------


@app.post("/vapi/tool/find-appointment")
async def tool_find_appointment(request: Request):
    body = await request.json()
    tool_call, args = _parse_tool_call(body)

    matches = appointment_store.find_appointment(
        patient_name=args["patient_name"],
        patient_dob=args.get("patient_dob", ""),
    )

    if not matches:
        text = (
            f"I don't see any upcoming appointments for {args['patient_name']}. "
            "Would you like to schedule one?"
        )
    else:
        lines = [
            f"ID {a['id']}: {a['appointment_type']} with {a['provider']} on {a['date']} at {a['time']}"
            for a in matches
        ]
        text = f"I found {len(matches)} upcoming appointment(s) for {args['patient_name']}:\n"
        text += "\n".join(lines)

    return _tool_response(tool_call, text)


# ---------------------------------------------------------------------------
# Tool: reschedule_appointment
# ---------------------------------------------------------------------------


@app.post("/vapi/tool/reschedule")
async def tool_reschedule(request: Request):
    body = await request.json()
    tool_call, args = _parse_tool_call(body)

    result = appointment_store.reschedule_appointment(
        appointment_id=args["appointment_id"],
        new_date=args["new_date"],
        new_time=args["new_time"],
    )

    if "error" in result:
        return _tool_response(tool_call, result["error"])

    appt = result["appointment"]
    text = (
        f"Your appointment has been rescheduled to {appt['date']} at {appt['time']} "
        f"with {appt['provider']}. Your confirmation number remains {appt['id']}."
    )
    logger.info("Appointment rescheduled: %s", appt)
    return _tool_response(tool_call, text)


# ---------------------------------------------------------------------------
# Tool: cancel_appointment
# ---------------------------------------------------------------------------


@app.post("/vapi/tool/cancel")
async def tool_cancel(request: Request):
    body = await request.json()
    tool_call, args = _parse_tool_call(body)

    result = appointment_store.cancel_appointment(
        appointment_id=args["appointment_id"],
        reason=args.get("reason", ""),
    )

    if "error" in result:
        return _tool_response(tool_call, result["error"])

    appt = result["appointment"]
    text = (
        f"Your appointment on {appt['date']} at {appt['time']} with {appt['provider']} "
        "has been cancelled. We're sorry to see you go — please don't hesitate to call "
        "us when you need to reschedule."
    )
    logger.info("Appointment cancelled: %s", appt["id"])
    return _tool_response(tool_call, text)


# ---------------------------------------------------------------------------
# Tool: request_prescription_refill
# ---------------------------------------------------------------------------


@app.post("/vapi/tool/refill")
async def tool_refill(request: Request):
    body = await request.json()
    tool_call, args = _parse_tool_call(body)

    # Screen for commonly controlled substance keywords
    med = args.get("medication_name", "").lower()
    controlled_keywords = ["adderall", "xanax", "oxycodone", "percocet", "valium",
                           "vicodin", "ambien", "klonopin", "ativan", "suboxone",
                           "tramadol", "hydrocodone", "alprazolam", "lorazepam",
                           "clonazepam", "diazepam", "morphine", "fentanyl"]
    if any(kw in med for kw in controlled_keywords):
        text = (
            "I'm sorry, but refill requests for controlled substances cannot be processed "
            "over the phone. Please schedule an appointment with your provider or contact "
            "the office directly during business hours."
        )
        return _tool_response(tool_call, text)

    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "type": "refill_request",
        "patient_name": args["patient_name"],
        "patient_dob": args.get("patient_dob", ""),
        "patient_phone": args["patient_phone"],
        "medication_name": args["medication_name"],
        "pharmacy_name": args["pharmacy_name"],
        "pharmacy_phone": args.get("pharmacy_phone", ""),
        "prescribing_provider": args.get("prescribing_provider", ""),
        "status": "pending",
    }
    refill_requests.append(entry)
    logger.info("Refill request logged: %s for %s", args["medication_name"], args["patient_name"])

    text = (
        f"I've submitted a refill request for {args['medication_name']} "
        f"to {args['pharmacy_name']}. "
        "Our clinical team will review and approve the request within 1–2 business days. "
        "If approved, the pharmacy will notify you when it's ready. "
        "If you need it sooner, please call us during business hours."
    )
    return _tool_response(tool_call, text)


# ---------------------------------------------------------------------------
# Tool: take_message
# ---------------------------------------------------------------------------


@app.post("/vapi/tool/message")
async def tool_message(request: Request):
    body = await request.json()
    tool_call, args = _parse_tool_call(body)

    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "type": "message",
        "patient_name": args.get("patient_name", "Unknown"),
        "patient_dob": args.get("patient_dob", ""),
        "patient_phone": args.get("patient_phone", "Not provided"),
        "message": args.get("message", ""),
        "urgency": args.get("urgency", "routine"),
    }
    messages_log.append(entry)
    logger.info("Message taken [%s]: %s", entry["urgency"], entry)

    urgency = entry["urgency"]
    if urgency == "urgent":
        eta = "as soon as possible, typically within 1–2 hours during business hours"
    elif urgency == "same-day":
        eta = "today during business hours"
    else:
        eta = "within 1–2 business days"

    text = (
        f"I've recorded your message, {entry['patient_name']}, and marked it as {urgency}. "
        f"A member of our care team will call you back at {entry['patient_phone']} {eta}. "
        "Is there anything else I can help you with?"
    )
    return _tool_response(tool_call, text)


# ---------------------------------------------------------------------------
# Tool: transfer_to_nurse
# ---------------------------------------------------------------------------


@app.post("/vapi/tool/transfer-nurse")
async def tool_transfer_nurse(request: Request):
    body = await request.json()
    tool_call, args = _parse_tool_call(body)

    twilio_sid = _twilio_sid(body)
    nurse_line = settings.nurse_line_number

    if not nurse_line:
        # No nurse line configured — take a message instead
        urgent_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "type": "nurse_message",
            "patient_name": args.get("patient_name", "Unknown"),
            "reason": args.get("reason", ""),
        }
        messages_log.append(urgent_entry)
        text = (
            "I'm sorry, our nurse line is not available right now. "
            "I've flagged your concern as urgent and a nurse will call you back shortly. "
            "If this is a medical emergency, please hang up and call 911."
        )
        return _tool_response(tool_call, text)

    if twilio_sid:
        try:
            twilio_client.transfer_call_to_agent(twilio_sid, args.get("reason", "Nurse requested"))
        except Exception as exc:
            logger.error("Nurse transfer failed: %s", exc)

    text = (
        f"Please hold, {args.get('patient_name', '')}. "
        "I'm connecting you with our nurse now."
    )
    return _tool_response(tool_call, text)


# ---------------------------------------------------------------------------
# Twilio webhooks
# ---------------------------------------------------------------------------


@app.post("/twilio/conference")
async def twilio_conference(request: Request, name: str = ""):
    twiml = twilio_client.conference_twiml(name or "default_conference")
    return Response(content=twiml, media_type="text/xml")


@app.post("/twilio/agent-status")
async def twilio_agent_status(
    request: Request,
    conference: str = "",
    caller_sid: str = "",
    CallStatus: str = Form(default=""),
):
    logger.info("Agent/nurse status: %s (conference=%s)", CallStatus, conference)
    if CallStatus in ("no-answer", "busy", "failed", "canceled") and caller_sid:
        try:
            client = twilio_client.get_twilio_client()
            client.calls(caller_sid).update(
                url=f"{settings.server_base_url}/twilio/unavailable",
                method="POST",
            )
        except Exception as exc:
            logger.error("Failed to redirect caller after no-answer: %s", exc)
    return PlainTextResponse("OK")


@app.post("/twilio/unavailable")
async def twilio_unavailable():
    twiml = twilio_client.agent_unavailable_twiml()
    return Response(content=twiml, media_type="text/xml")


@app.post("/twilio/voicemail")
async def twilio_voicemail(
    RecordingUrl: str = Form(default=""),
    RecordingSid: str = Form(default=""),
    From: str = Form(default=""),
):
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "type": "voicemail",
        "caller_number": From,
        "recording_url": RecordingUrl,
        "recording_sid": RecordingSid,
    }
    messages_log.append(entry)
    logger.info("Voicemail received from %s", From)

    from twilio.twiml.voice_response import VoiceResponse
    response = VoiceResponse()
    response.say(
        "Thank you for your message. Our team will follow up with you as soon as possible. Goodbye.",
        voice="Polly.Joanna",
    )
    response.hangup()
    return Response(content=str(response), media_type="text/xml")


# ---------------------------------------------------------------------------
# Admin / Staff endpoints
# ---------------------------------------------------------------------------


@app.get("/admin/appointments")
async def admin_appointments(date: str | None = None, status: str = "scheduled"):
    """List appointments. Filter by date (YYYY-MM-DD) and status."""
    appts = list(appointment_store.appointments.values())
    if date:
        appts = [a for a in appts if a["date"] == date]
    if status:
        appts = [a for a in appts if a["status"] == status]
    appts.sort(key=lambda a: (a["date"], a["time"]))
    return JSONResponse(appts)


@app.get("/admin/messages")
async def admin_messages():
    """View all messages, voicemails, and nurse-line flags."""
    return JSONResponse(messages_log)


@app.get("/admin/refills")
async def admin_refills():
    """View all pending prescription refill requests."""
    return JSONResponse(refill_requests)


@app.patch("/admin/refills/{idx}/approve")
async def admin_approve_refill(idx: int):
    """Mark a refill request as approved."""
    if idx < 0 or idx >= len(refill_requests):
        raise HTTPException(status_code=404, detail="Refill request not found")
    refill_requests[idx]["status"] = "approved"
    refill_requests[idx]["approved_at"] = datetime.utcnow().isoformat()
    return JSONResponse(refill_requests[idx])


@app.post("/admin/call")
async def admin_outbound_call(request: Request):
    """Trigger an outbound AI call. Body: {"to": "+1XXXXXXXXXX"}"""
    body = await request.json()
    to_number = body.get("to")
    if not to_number:
        raise HTTPException(status_code=400, detail="'to' phone number is required")
    result = vapi_client.create_outbound_call(to_number)
    return JSONResponse(result)


@app.get("/admin/calls")
async def admin_list_calls(limit: int = 20):
    """List recent calls from Vapi."""
    return JSONResponse(vapi_client.list_calls(limit=limit))
