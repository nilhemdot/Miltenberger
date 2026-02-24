"""
Doctor's Office AI Receptionist — FastAPI server

Handles:
  - After-hours detection (middleware)
  - Vapi assistant lifecycle events
  - Vapi tool call webhooks (scheduling, refills, insurance, waitlist, billing, etc.)
  - Twilio call routing (conference, voicemail, status callbacks)
  - Admin / staff API endpoints

HIPAA note: This server logs call data to memory only. For production,
ensure all storage is encrypted at rest, access-controlled, and
compliant with HIPAA's Technical Safeguards (45 CFR § 164.312).
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from app import (
    after_hours,
    appointment_store,
    insurance,
    sms,
    twilio_client,
    vapi_client,
    waitlist,
)
from app.config import settings
from app.scheduler import get_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# App lifespan — start/stop APScheduler
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = get_scheduler()
    scheduler.start()
    logger.info("Scheduler started with %d jobs", len(scheduler.get_jobs()))
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(
    title="Doctor's Office AI Receptionist",
    version="3.0.0",
    lifespan=lifespan,
)

# In-memory logs — replace with encrypted DB in production
messages_log: list[dict] = []
refill_requests: list[dict] = []
call_log: list[dict] = []


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _parse_tool_call(body: dict) -> tuple[dict, dict]:
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
    return (
        body.get("message", {})
        .get("call", {})
        .get("phoneCallProviderDetails", {})
        .get("callSid", "")
    )


# ---------------------------------------------------------------------------
# After-hours middleware
# Intercepts Twilio inbound calls and redirects them if outside business hours.
# Note: Vapi itself handles the call pickup — this middleware catches any
# direct Twilio status/fallback webhooks. After-hours routing for the
# AI assistant is also enforced in the system prompt via business hours context.
# ---------------------------------------------------------------------------

@app.middleware("http")
async def after_hours_middleware(request: Request, call_next):
    # Only intercept the Twilio entry points that need after-hours gating
    gated_paths = {"/twilio/inbound"}
    if request.url.path in gated_paths and not after_hours.is_business_hours():
        twiml = after_hours.after_hours_twiml()
        return Response(content=twiml, media_type="text/xml")
    return await call_next(request)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "practice": settings.business_name,
        "business_hours_now": after_hours.is_business_hours(),
        "appointments_today": sum(
            1 for a in appointment_store.appointments.values()
            if a["date"] == datetime.utcnow().date().isoformat()
            and a["status"] == "scheduled"
        ),
        "waitlist_count": len(waitlist.get_waitlist()),
        "pending_refills": sum(1 for r in refill_requests if r.get("status") == "pending"),
    }


# ---------------------------------------------------------------------------
# Optional Twilio inbound entry point (if not using Vapi's direct pickup)
# ---------------------------------------------------------------------------

@app.post("/twilio/inbound")
async def twilio_inbound():
    """
    Fallback inbound handler — after_hours_middleware handles after-hours.
    During hours, Vapi takes the call directly via the imported phone number,
    so this endpoint is only reached if you configure your Twilio webhook here.
    """
    from twilio.twiml.voice_response import VoiceResponse
    response = VoiceResponse()
    response.say("Please hold while we connect you.", voice="Polly.Joanna")
    return Response(content=str(response), media_type="text/xml")


# ---------------------------------------------------------------------------
# Vapi lifecycle webhook
# ---------------------------------------------------------------------------

@app.post("/vapi/webhook")
async def vapi_webhook(request: Request):
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
        text = (
            "I'm sorry, there are no available slots in the next 5 business days "
            "for your request. Would you like me to add you to our waitlist? "
            "We'll text you as soon as a slot opens up."
        )
    else:
        lines = []
        for day, providers in list(available.items())[:3]:
            for prov_info in providers:
                times_str = ", ".join(prov_info["times"][:4])
                lines.append(f"{day} with {prov_info['provider']}: {times_str}")
        text = "Here are our next available appointments:\n" + "\n".join(lines)
        text += f"\n\nVisit types available: {', '.join(result['appointment_types'][:4])}, and more."

    return _tool_response(tool_call, text)


# ---------------------------------------------------------------------------
# Tool: schedule_appointment
# ---------------------------------------------------------------------------

@app.post("/vapi/tool/schedule")
async def tool_schedule(request: Request):
    body = await request.json()
    tool_call, args = _parse_tool_call(body)

    is_new = args.get("is_new_patient", False)
    result = appointment_store.schedule_appointment(
        patient_name=args["patient_name"],
        patient_dob=args["patient_dob"],
        patient_phone=args["patient_phone"],
        provider=args["provider"],
        appointment_type=args["appointment_type"],
        date_str=args["date"],
        time_str=args["time"],
        notes=args.get("notes", ""),
        is_new_patient=is_new,
    )

    if "error" in result:
        return _tool_response(tool_call, result["error"])

    appt = result["appointment"]
    text = (
        f"Your appointment is confirmed! "
        f"{appt['appointment_type']} with {appt['provider']} on "
        f"{appt['date']} at {appt['time']}. "
        f"Confirmation number: {appt['id']}. "
        f"I've sent a confirmation text to the number on file. "
        f"Please arrive 15 minutes early with your insurance card and a photo ID."
    )
    if is_new:
        text += (
            " Since you're a new patient, you'll also receive a link to complete "
            "your intake forms before your visit."
        )

    logger.info("Appointment scheduled: %s", appt["id"])
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
        text = f"I found {len(matches)} upcoming appointment(s):\n" + "\n".join(lines)

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
        f"with {appt['provider']}. Confirmation number: {appt['id']}. "
        f"You'll receive an updated confirmation text shortly."
    )
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
        "has been cancelled. You'll receive a cancellation confirmation by text. "
        "Would you like me to add you to our waitlist for an earlier opening, "
        "or would you like to schedule a new appointment?"
    )
    return _tool_response(tool_call, text)


# ---------------------------------------------------------------------------
# Tool: request_prescription_refill
# ---------------------------------------------------------------------------

@app.post("/vapi/tool/refill")
async def tool_refill(request: Request):
    body = await request.json()
    tool_call, args = _parse_tool_call(body)

    med = args.get("medication_name", "").lower()
    controlled_keywords = [
        "adderall", "ritalin", "vyvanse", "xanax", "valium", "ativan", "klonopin",
        "oxycodone", "percocet", "vicodin", "hydrocodone", "morphine", "fentanyl",
        "suboxone", "methadone", "tramadol", "ambien", "lunesta", "soma",
        "alprazolam", "lorazepam", "clonazepam", "diazepam",
    ]
    if any(kw in med for kw in controlled_keywords):
        return _tool_response(
            tool_call,
            "I'm sorry, refill requests for controlled substances cannot be processed "
            "over the phone. Please schedule an appointment with your provider or "
            "contact the office directly during business hours.",
        )

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
    logger.info("Refill request: %s for %s", args["medication_name"], args["patient_name"])

    return _tool_response(
        tool_call,
        f"I've submitted a refill request for {args['medication_name']} "
        f"to {args['pharmacy_name']}. "
        "Our clinical team will review it within 1–2 business days. "
        "The pharmacy will notify you when it's ready. "
        "You'll receive a text confirmation once approved.",
    )


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
        "patient_phone": args.get("patient_phone", ""),
        "message": args.get("message", ""),
        "urgency": args.get("urgency", "routine"),
    }
    messages_log.append(entry)
    logger.info("Message [%s]: %s", entry["urgency"], entry["patient_name"])

    eta_map = {
        "urgent": "as soon as possible, typically within 1–2 hours during business hours",
        "same-day": "today during business hours",
        "routine": "within 1–2 business days",
    }
    eta = eta_map.get(entry["urgency"], "within 1–2 business days")

    return _tool_response(
        tool_call,
        f"I've recorded your message and flagged it as {entry['urgency']}. "
        f"A member of our care team will call you back at {entry['patient_phone']} {eta}. "
        "Is there anything else I can help you with?",
    )


# ---------------------------------------------------------------------------
# Tool: transfer_to_nurse
# ---------------------------------------------------------------------------

@app.post("/vapi/tool/transfer-nurse")
async def tool_transfer_nurse(request: Request):
    body = await request.json()
    tool_call, args = _parse_tool_call(body)
    twilio_sid = _twilio_sid(body)

    if not settings.nurse_line_number:
        urgent_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "type": "nurse_callback",
            "patient_name": args.get("patient_name", "Unknown"),
            "reason": args.get("reason", ""),
            "urgency": "urgent",
        }
        messages_log.append(urgent_entry)
        return _tool_response(
            tool_call,
            "Our nurse line is not available right now. "
            "I've flagged your concern as urgent — a nurse will call you back shortly. "
            "If this is a medical emergency, please hang up and call 911.",
        )

    if twilio_sid:
        try:
            twilio_client.transfer_call_to_agent(twilio_sid, args.get("reason", "Nurse requested"))
        except Exception as exc:
            logger.error("Nurse transfer failed: %s", exc)

    return _tool_response(
        tool_call,
        f"Please hold, {args.get('patient_name', '')}. I'm connecting you with our nurse now.",
    )


# ---------------------------------------------------------------------------
# Tool: collect_insurance_info
# ---------------------------------------------------------------------------

@app.post("/vapi/tool/collect-insurance")
async def tool_collect_insurance(request: Request):
    body = await request.json()
    tool_call, args = _parse_tool_call(body)

    record = insurance.save_insurance(
        patient_name=args["patient_name"],
        patient_dob=args["patient_dob"],
        primary_provider=args["primary_provider"],
        member_id=args["member_id"],
        group_number=args.get("group_number", ""),
        policy_holder_name=args.get("policy_holder_name", ""),
        plan_name=args.get("plan_name", ""),
        secondary_provider=args.get("secondary_provider", ""),
        secondary_member_id=args.get("secondary_member_id", ""),
    )

    logger.info("Insurance saved for %s", args["patient_name"])
    return _tool_response(
        tool_call,
        f"Thank you. I've recorded your {args['primary_provider']} insurance "
        f"with member ID ending in {args['member_id'][-4:]}. "
        "Our billing team will verify your coverage before your appointment.",
    )


# ---------------------------------------------------------------------------
# Tool: add_to_waitlist
# ---------------------------------------------------------------------------

@app.post("/vapi/tool/waitlist")
async def tool_waitlist(request: Request):
    body = await request.json()
    tool_call, args = _parse_tool_call(body)

    entry = waitlist.add_to_waitlist(
        patient_name=args["patient_name"],
        patient_dob=args["patient_dob"],
        patient_phone=args["patient_phone"],
        appointment_type=args["appointment_type"],
        provider=args.get("preferred_provider"),
        preferred_dates=args.get("preferred_dates", []),
        notes=args.get("notes", ""),
    )

    logger.info("Added to waitlist: %s (ID %s)", args["patient_name"], entry["id"])
    return _tool_response(
        tool_call,
        f"I've added you to our waitlist, {args['patient_name']}. "
        f"Your waitlist ID is {entry['id']}. "
        "We'll send you a text message the moment a matching appointment opens up. "
        "The slot will be held for 2 hours after we notify you.",
    )


# ---------------------------------------------------------------------------
# Tool: billing_question
# ---------------------------------------------------------------------------

@app.post("/vapi/tool/billing")
async def tool_billing(request: Request):
    body = await request.json()
    tool_call, args = _parse_tool_call(body)
    twilio_sid = _twilio_sid(body)

    transfer_now = args.get("transfer_now", False)

    # Log the billing question regardless
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "type": "billing_question",
        "patient_name": args["patient_name"],
        "patient_phone": args["patient_phone"],
        "question": args["question"],
        "status": "pending",
    }
    messages_log.append(entry)
    logger.info("Billing question from %s: %s", args["patient_name"], args["question"])

    if transfer_now and settings.billing_line_number and twilio_sid:
        try:
            twilio_client.transfer_call_to_agent(twilio_sid, "Billing question: " + args["question"])
        except Exception as exc:
            logger.error("Billing transfer failed: %s", exc)
        return _tool_response(
            tool_call,
            "I'm transferring you to our billing department now. Please hold.",
        )

    return _tool_response(
        tool_call,
        "I've noted your billing question and a member of our billing team will "
        f"call you back at {args['patient_phone']} within 1–2 business days. "
        "If you need to reach billing directly, you can call us during business hours "
        f"at {settings.twilio_phone_number}.",
    )


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
    logger.info("Voicemail from %s — recording %s", From, RecordingSid)

    from twilio.twiml.voice_response import VoiceResponse
    response = VoiceResponse()
    response.say(
        "Thank you for your message. Our team will follow up as soon as possible. Goodbye.",
        voice="Polly.Joanna",
    )
    response.hangup()
    return Response(content=str(response), media_type="text/xml")


# ---------------------------------------------------------------------------
# Admin / Staff API
# ---------------------------------------------------------------------------

@app.get("/admin/appointments")
async def admin_appointments(date: str | None = None, status: str = "scheduled"):
    appts = list(appointment_store.appointments.values())
    if date:
        appts = [a for a in appts if a["date"] == date]
    if status:
        appts = [a for a in appts if a["status"] == status]
    appts.sort(key=lambda a: (a["date"], a["time"]))
    return JSONResponse(appts)


@app.get("/admin/messages")
async def admin_messages():
    return JSONResponse(messages_log)


@app.get("/admin/refills")
async def admin_refills():
    return JSONResponse(refill_requests)


@app.patch("/admin/refills/{idx}/approve")
async def admin_approve_refill(idx: int):
    if idx < 0 or idx >= len(refill_requests):
        raise HTTPException(status_code=404, detail="Not found")
    entry = refill_requests[idx]
    entry["status"] = "approved"
    entry["approved_at"] = datetime.utcnow().isoformat()
    # Send SMS to patient
    sms.send_refill_approved(
        entry.get("patient_phone", ""),
        entry["patient_name"],
        entry["medication_name"],
        entry["pharmacy_name"],
    )
    return JSONResponse(entry)


@app.get("/admin/waitlist")
async def admin_waitlist(status: str = "waiting"):
    return JSONResponse(waitlist.get_waitlist(status))


@app.delete("/admin/waitlist/{waitlist_id}")
async def admin_remove_waitlist(waitlist_id: str):
    removed = waitlist.remove_from_waitlist(waitlist_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Waitlist entry not found")
    return JSONResponse({"removed": waitlist_id})


@app.get("/admin/insurance")
async def admin_insurance():
    return JSONResponse(insurance.get_all_unverified())


@app.patch("/admin/insurance/verify")
async def admin_verify_insurance(request: Request):
    body = await request.json()
    ok = insurance.mark_verified(body["patient_name"], body["patient_dob"])
    if not ok:
        raise HTTPException(status_code=404, detail="Insurance record not found")
    return JSONResponse({"verified": True})


@app.post("/admin/lab-results")
async def admin_lab_results(request: Request):
    """
    Staff endpoint to notify a patient that their lab results are ready.
    Body: {"patient_name": "...", "patient_phone": "...", "provider": "..."}
    """
    body = await request.json()
    sent = sms.send_lab_results_ready(
        phone=body["patient_phone"],
        patient_name=body["patient_name"],
        provider=body.get("provider", "your provider"),
    )
    return JSONResponse({"sms_sent": sent})


@app.post("/admin/call")
async def admin_outbound_call(request: Request):
    """Trigger an outbound AI call. Body: {"to": "+1XXXXXXXXXX"}"""
    body = await request.json()
    to_number = body.get("to")
    if not to_number:
        raise HTTPException(status_code=400, detail="'to' is required")
    result = vapi_client.create_outbound_call(to_number)
    return JSONResponse(result)


@app.get("/admin/calls")
async def admin_list_calls(limit: int = 20):
    return JSONResponse(vapi_client.list_calls(limit=limit))


@app.get("/admin/scheduler/jobs")
async def admin_scheduler_jobs():
    """List scheduled background jobs and their next run times."""
    scheduler = get_scheduler()
    jobs = [
        {
            "id": job.id,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
        }
        for job in scheduler.get_jobs()
    ]
    return JSONResponse(jobs)
