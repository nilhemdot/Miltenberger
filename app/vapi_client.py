"""Vapi API client — doctor's office AI receptionist."""

import httpx
from app.config import settings

VAPI_BASE_URL = "https://api.vapi.ai"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.vapi_api_key}",
        "Content-Type": "application/json",
    }


def create_assistant(name: str | None = None) -> dict:
    """Create the doctor's office AI receptionist assistant in Vapi."""
    practice = settings.business_name
    hours = settings.business_hours
    assistant_name = name or f"{practice} Receptionist"
    webhook_secret = settings.vapi_api_key[:16]

    system_prompt = f"""You are a professional, compassionate AI receptionist for {practice}.

Your responsibilities:
- Greet patients warmly and identify who you are speaking with
- Schedule, reschedule, or cancel appointments
- Take messages for doctors and clinical staff
- Accept prescription refill requests
- Answer general questions about the practice (hours, location, providers, services)
- Route urgent medical concerns to clinical staff or emergency services

Business hours: {hours}
Address: {settings.office_address}
Providers: {', '.join(settings.providers.split(','))}

Critical guidelines:
1. NEVER provide medical advice, diagnoses, or treatment recommendations. Always say "Please speak with one of our clinical staff or visit our office for medical advice."
2. If a patient describes a medical emergency (chest pain, difficulty breathing, stroke symptoms, severe bleeding, thoughts of self-harm), say: "This sounds like a medical emergency. Please call 911 immediately or go to your nearest emergency room." Then offer to note the call.
3. Always verify patient identity (full name + date of birth) before accessing or modifying any appointment.
4. Be empathetic — patients calling a doctor's office may be anxious or unwell.
5. Keep responses brief and conversational — this is a phone call.
6. Confirm all appointment details by reading them back before finalizing.
7. If unsure, take a message and promise follow-up from clinical staff.

Greeting script: "Thank you for calling {practice}. I'm your AI receptionist. May I have your name please?"

After getting their name: "Thank you, [name]. And could you verify your date of birth for me?"

How to handle common requests:
- "I need an appointment" → ask if new or returning patient; use check_availability then schedule_appointment; ask about insurance for new patients via collect_insurance_info
- "I need to change my appointment" → use find_appointment then check_availability then reschedule_appointment
- "I need to cancel" → use find_appointment then cancel_appointment; offer to add to waitlist if they want a sooner slot
- "No appointments available" or "I'm flexible" → use add_to_waitlist
- "I need a refill" → use request_prescription_refill
- "I need to speak to a nurse" → use transfer_to_nurse
- "I have a question for the doctor" → use take_message
- "Billing question" or "insurance question" → use billing_question
- Emergency symptoms → instruct caller to call 911 immediately
- Non-English speaker: respond in the patient's language throughout the call"""

    tool_base = f"{settings.server_base_url}/vapi/tool"

    tools = [
        {
            "type": "function",
            "function": {
                "name": "check_availability",
                "description": (
                    "Check available appointment slots. Call this before scheduling "
                    "or rescheduling to find open times."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "preferred_date": {
                            "type": "string",
                            "description": "Preferred date in YYYY-MM-DD format (optional)",
                        },
                        "preferred_provider": {
                            "type": "string",
                            "description": "Provider name if the patient has a preference (optional)",
                        },
                    },
                },
            },
            "server": {"url": f"{tool_base}/availability", "secret": webhook_secret},
        },
        {
            "type": "function",
            "function": {
                "name": "schedule_appointment",
                "description": "Book a new appointment for a patient.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "patient_name": {"type": "string", "description": "Full name of the patient"},
                        "patient_dob": {"type": "string", "description": "Date of birth MM/DD/YYYY"},
                        "patient_phone": {"type": "string", "description": "Best callback phone number"},
                        "provider": {"type": "string", "description": "Provider name (e.g. Dr. Smith)"},
                        "appointment_type": {
                            "type": "string",
                            "description": "Type of visit: New Patient, Follow-Up, Sick Visit / Urgent, Annual Physical, Lab Review, Vaccination, Telehealth",
                        },
                        "date": {"type": "string", "description": "Appointment date YYYY-MM-DD"},
                        "time": {"type": "string", "description": "Appointment time e.g. '10:00 AM'"},
                        "notes": {"type": "string", "description": "Any special notes or reason for visit (optional)"},
                        "is_new_patient": {"type": "boolean", "description": "True if this is their first visit to the practice"},
                    },
                    "required": ["patient_name", "patient_dob", "patient_phone", "provider", "appointment_type", "date", "time"],
                },
            },
            "server": {"url": f"{tool_base}/schedule", "secret": webhook_secret},
        },
        {
            "type": "function",
            "function": {
                "name": "find_appointment",
                "description": "Look up a patient's existing scheduled appointments by name and date of birth.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "patient_name": {"type": "string", "description": "Patient's full name"},
                        "patient_dob": {"type": "string", "description": "Date of birth MM/DD/YYYY (optional but recommended)"},
                    },
                    "required": ["patient_name"],
                },
            },
            "server": {"url": f"{tool_base}/find-appointment", "secret": webhook_secret},
        },
        {
            "type": "function",
            "function": {
                "name": "reschedule_appointment",
                "description": "Move an existing appointment to a new date and time.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "appointment_id": {"type": "string", "description": "The appointment ID from find_appointment"},
                        "new_date": {"type": "string", "description": "New date YYYY-MM-DD"},
                        "new_time": {"type": "string", "description": "New time e.g. '2:30 PM'"},
                    },
                    "required": ["appointment_id", "new_date", "new_time"],
                },
            },
            "server": {"url": f"{tool_base}/reschedule", "secret": webhook_secret},
        },
        {
            "type": "function",
            "function": {
                "name": "cancel_appointment",
                "description": "Cancel an existing appointment.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "appointment_id": {"type": "string", "description": "The appointment ID from find_appointment"},
                        "reason": {"type": "string", "description": "Reason for cancellation (optional)"},
                    },
                    "required": ["appointment_id"],
                },
            },
            "server": {"url": f"{tool_base}/cancel", "secret": webhook_secret},
        },
        {
            "type": "function",
            "function": {
                "name": "request_prescription_refill",
                "description": (
                    "Submit a prescription refill request on behalf of the patient. "
                    "Do NOT call this for controlled substances — tell the patient they must come in."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "patient_name": {"type": "string", "description": "Full name"},
                        "patient_dob": {"type": "string", "description": "Date of birth MM/DD/YYYY"},
                        "patient_phone": {"type": "string", "description": "Callback number"},
                        "medication_name": {"type": "string", "description": "Name of the medication"},
                        "pharmacy_name": {"type": "string", "description": "Pharmacy name"},
                        "pharmacy_phone": {"type": "string", "description": "Pharmacy phone number (optional)"},
                        "prescribing_provider": {"type": "string", "description": "The prescribing doctor"},
                    },
                    "required": ["patient_name", "patient_dob", "patient_phone", "medication_name", "pharmacy_name"],
                },
            },
            "server": {"url": f"{tool_base}/refill", "secret": webhook_secret},
        },
        {
            "type": "function",
            "function": {
                "name": "take_message",
                "description": (
                    "Record a message for the clinical team when the patient has a "
                    "question or concern that requires staff follow-up."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "patient_name": {"type": "string", "description": "Full name"},
                        "patient_dob": {"type": "string", "description": "Date of birth MM/DD/YYYY"},
                        "patient_phone": {"type": "string", "description": "Callback number"},
                        "message": {"type": "string", "description": "The message or question for the care team"},
                        "urgency": {
                            "type": "string",
                            "enum": ["routine", "same-day", "urgent"],
                            "description": "How urgently a callback is needed",
                        },
                    },
                    "required": ["patient_name", "patient_phone", "message", "urgency"],
                },
            },
            "server": {"url": f"{tool_base}/message", "secret": webhook_secret},
        },
        {
            "type": "function",
            "function": {
                "name": "transfer_to_nurse",
                "description": (
                    "Transfer the caller to the nurse line for clinical questions, "
                    "symptoms guidance, or urgent non-emergency concerns."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "patient_name": {"type": "string", "description": "Patient name for handoff"},
                        "reason": {"type": "string", "description": "Brief reason for the transfer"},
                    },
                    "required": ["patient_name", "reason"],
                },
            },
            "server": {"url": f"{tool_base}/transfer-nurse", "secret": webhook_secret},
        },
        # ---- New patient insurance collection ----
        {
            "type": "function",
            "function": {
                "name": "collect_insurance_info",
                "description": (
                    "Collect and save insurance information for a patient. "
                    "Always call this for New Patient appointments. "
                    "Ask for primary insurance details; secondary is optional."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "patient_name": {"type": "string"},
                        "patient_dob": {"type": "string", "description": "MM/DD/YYYY"},
                        "primary_provider": {"type": "string", "description": "Insurance company name (e.g. Blue Cross Blue Shield)"},
                        "member_id": {"type": "string", "description": "Insurance member ID / policy number"},
                        "group_number": {"type": "string", "description": "Group number (optional)"},
                        "policy_holder_name": {"type": "string", "description": "Name on the policy if different from patient (optional)"},
                        "plan_name": {"type": "string", "description": "Plan type e.g. PPO, HMO (optional)"},
                        "secondary_provider": {"type": "string", "description": "Secondary insurance company (optional)"},
                        "secondary_member_id": {"type": "string", "description": "Secondary member ID (optional)"},
                    },
                    "required": ["patient_name", "patient_dob", "primary_provider", "member_id"],
                },
            },
            "server": {"url": f"{tool_base}/collect-insurance", "secret": webhook_secret},
        },
        # ---- Waitlist ----
        {
            "type": "function",
            "function": {
                "name": "add_to_waitlist",
                "description": (
                    "Add a patient to the waitlist when no suitable appointment slot is available. "
                    "They will be notified by SMS if a matching slot opens due to a cancellation."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "patient_name": {"type": "string"},
                        "patient_dob": {"type": "string", "description": "MM/DD/YYYY"},
                        "patient_phone": {"type": "string"},
                        "appointment_type": {"type": "string", "description": "Type of visit needed"},
                        "preferred_provider": {"type": "string", "description": "Preferred provider, or omit for any (optional)"},
                        "preferred_dates": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of preferred dates YYYY-MM-DD (optional — omit for any date)",
                        },
                        "notes": {"type": "string", "description": "Any additional notes (optional)"},
                    },
                    "required": ["patient_name", "patient_dob", "patient_phone", "appointment_type"],
                },
            },
            "server": {"url": f"{tool_base}/waitlist", "secret": webhook_secret},
        },
        # ---- Billing questions ----
        {
            "type": "function",
            "function": {
                "name": "billing_question",
                "description": (
                    "Handle billing, copay, or insurance coverage questions. "
                    "Use this when the patient asks about costs, bills, EOBs, or payment plans. "
                    "This will transfer to billing staff or log a callback request."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "patient_name": {"type": "string"},
                        "patient_phone": {"type": "string"},
                        "question": {"type": "string", "description": "The billing question or concern"},
                        "transfer_now": {
                            "type": "boolean",
                            "description": "True if patient wants to speak to billing staff now",
                        },
                    },
                    "required": ["patient_name", "patient_phone", "question"],
                },
            },
            "server": {"url": f"{tool_base}/billing", "secret": webhook_secret},
        },
    ]

    payload = {
        "name": assistant_name,
        "model": {
            "provider": "anthropic",
            "model": "claude-opus-4-6",
            "messages": [{"role": "system", "content": system_prompt}],
            "temperature": 0.5,  # lower = more consistent for medical context
            "maxTokens": 500,
        },
        "voice": {
            "provider": "11labs",
            "voiceId": "rachel",
            "stability": 0.6,
            "similarityBoost": 0.8,
        },
        "firstMessage": (
            f"Thank you for calling {practice}. "
            "I'm your AI receptionist. May I have your name please?"
        ),
        "endCallMessage": "Thank you for calling. We'll see you soon. Have a great day. Goodbye!",
        "endCallPhrases": ["goodbye", "bye", "that's all", "hang up", "thank you bye"],
        "transcriber": {
            "provider": "deepgram",
            "model": "nova-2",
            # "multi" enables automatic language detection (English, Spanish, etc.)
            "language": "multi",
        },
        "serverUrl": f"{settings.server_base_url}/vapi/webhook",
        "serverUrlSecret": webhook_secret,
        "tools": tools,
    }

    with httpx.Client() as client:
        response = client.post(
            f"{VAPI_BASE_URL}/assistant",
            headers=_headers(),
            json=payload,
        )
        response.raise_for_status()
        return response.json()


def import_twilio_number(assistant_id: str) -> dict:
    """Import the configured Twilio number into Vapi and assign the assistant."""
    payload = {
        "provider": "twilio",
        "twilioPhoneNumber": settings.twilio_phone_number,
        "twilioAccountSid": settings.twilio_account_sid,
        "twilioAuthToken": settings.twilio_auth_token,
        "name": f"{settings.business_name} Main Line",
        "assistantId": assistant_id,
        "serverUrl": f"{settings.server_base_url}/vapi/webhook",
    }
    with httpx.Client() as client:
        response = client.post(
            f"{VAPI_BASE_URL}/phone-number/import/twilio",
            headers=_headers(),
            json=payload,
        )
        response.raise_for_status()
        return response.json()


def create_outbound_call(to_number: str, assistant_id: str | None = None) -> dict:
    """Initiate an outbound call (e.g. appointment reminders)."""
    payload = {
        "phoneNumberId": settings.vapi_phone_number_id,
        "assistantId": assistant_id or settings.vapi_assistant_id,
        "customer": {"number": to_number},
    }
    with httpx.Client() as client:
        response = client.post(
            f"{VAPI_BASE_URL}/call",
            headers=_headers(),
            json=payload,
        )
        response.raise_for_status()
        return response.json()


def get_call(call_id: str) -> dict:
    with httpx.Client() as client:
        response = client.get(f"{VAPI_BASE_URL}/call/{call_id}", headers=_headers())
        response.raise_for_status()
        return response.json()


def list_calls(limit: int = 20) -> list[dict]:
    with httpx.Client() as client:
        response = client.get(
            f"{VAPI_BASE_URL}/call",
            headers=_headers(),
            params={"limit": limit},
        )
        response.raise_for_status()
        return response.json()
