# Doctor's Office AI Receptionist — Vapi + Twilio + Claude

An AI-powered phone receptionist for medical practices. Patients can call to schedule, reschedule, or cancel appointments, request prescription refills, leave messages for clinical staff, or be transferred to a nurse — all handled by a conversational AI powered by **Claude** via **Vapi**, with **Twilio** for telephony.

> **HIPAA Notice:** This server stores call data in memory only. For production deployments, all patient data must be stored in an encrypted, access-controlled system compliant with HIPAA's Technical Safeguards (45 CFR § 164.312). Integrate with a compliant EHR (e.g. Epic, Athena Health) instead of the in-memory appointment store.

---

## Call Flow

```
Patient calls Twilio number
        ↓
Vapi answers → Claude AI Receptionist
        ↓
  ┌─────┴──────────────────────────────────────────────┐
  │                                                    │
Schedule / Reschedule /         Prescription Refill /
Cancel Appointment              Leave Message for Staff
  │                                                    │
  ↓                                                    ↓
Appointment Store           Message / Refill Log
(EHR API in production)     (Database in production)
  │
  └──── Transfer to Nurse / Operator
              ↓
       Twilio Conference Room
              ↓
       Human Staff Line
              ↓ (if no answer)
       Voicemail Recording
```

---

## Features

| Feature | Description |
|---|---|
| **Schedule appointments** | Checks availability, collects patient info, books & confirms |
| **Reschedule appointments** | Looks up existing appt, finds new slot, updates booking |
| **Cancel appointments** | Cancels by ID with reason, frees the slot |
| **Prescription refills** | Takes refill requests; blocks controlled substances automatically |
| **Leave a message** | Urgency-flagged messages for care team follow-up |
| **Transfer to nurse** | Live transfer via Twilio conference for clinical questions |
| **Voicemail fallback** | Records message if nurse/agent doesn't answer |
| **Emergency detection** | Instructs patient to call 911 for emergency symptoms |
| **Admin API** | View appointments, messages, refill requests; trigger outbound calls |

---

## Prerequisites

- [Vapi account](https://vapi.ai) with API key
- [Twilio account](https://twilio.com) with a phone number
- [Anthropic API key](https://console.anthropic.com) (Claude as LLM inside Vapi)
- Python 3.11+
- A public HTTPS URL ([ngrok](https://ngrok.com) for development)

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your credentials and practice details
```

Key variables:

| Variable | Description |
|---|---|
| `VAPI_API_KEY` | Vapi dashboard API key |
| `TWILIO_ACCOUNT_SID` | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | Twilio auth token |
| `TWILIO_PHONE_NUMBER` | Your Twilio phone number (E.164) |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `SERVER_BASE_URL` | Public HTTPS URL of this server |
| `BUSINESS_NAME` | Your practice name |
| `BUSINESS_HOURS` | Office hours (included in AI system prompt) |
| `OFFICE_ADDRESS` | Physical address for patients |
| `PROVIDERS` | Comma-separated provider names |
| `NURSE_LINE_NUMBER` | Clinical nurse triage number |
| `HUMAN_AGENT_NUMBER` | Front desk direct line |
| `AFTER_HOURS_NUMBER` | On-call / answering service |

### 3. Start the server

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

For local development, expose with ngrok:

```bash
ngrok http 8000
# Paste the https:// URL into SERVER_BASE_URL in .env
```

### 4. Create the Vapi assistant (one-time)

```bash
python scripts/setup_assistant.py
# Copy VAPI_ASSISTANT_ID printed to .env
```

### 5. Import your Twilio number into Vapi (one-time)

```bash
python scripts/setup_phone.py
# Copy VAPI_PHONE_NUMBER_ID printed to .env
```

**Done.** Call your Twilio number — Claude will answer as your receptionist.

---

## API Reference

### Vapi Tool Webhooks
| Path | Tool | Description |
|---|---|---|
| `POST /vapi/tool/availability` | `check_availability` | Returns open appointment slots |
| `POST /vapi/tool/schedule` | `schedule_appointment` | Books a new appointment |
| `POST /vapi/tool/find-appointment` | `find_appointment` | Looks up patient's appointments |
| `POST /vapi/tool/reschedule` | `reschedule_appointment` | Moves appointment to new slot |
| `POST /vapi/tool/cancel` | `cancel_appointment` | Cancels an appointment |
| `POST /vapi/tool/refill` | `request_prescription_refill` | Logs a refill request |
| `POST /vapi/tool/message` | `take_message` | Records message for care team |
| `POST /vapi/tool/transfer-nurse` | `transfer_to_nurse` | Transfers call to nurse line |

### Twilio Webhooks
| Path | Description |
|---|---|
| `POST /twilio/conference` | TwiML: join conference room |
| `POST /twilio/agent-status` | Status callback when agent leg completes |
| `POST /twilio/unavailable` | TwiML: agent unavailable → voicemail |
| `POST /twilio/voicemail` | Receives voicemail recording details |

### Admin / Staff API
| Path | Description |
|---|---|
| `GET /health` | Server health + today's appointment count |
| `GET /admin/appointments?date=YYYY-MM-DD` | List appointments (filter by date/status) |
| `GET /admin/messages` | All messages, voicemails, nurse flags |
| `GET /admin/refills` | All pending refill requests |
| `PATCH /admin/refills/{idx}/approve` | Approve a refill request |
| `POST /admin/call` | Trigger outbound AI call `{"to":"+1..."}` |
| `GET /admin/calls` | Recent call history from Vapi |

---

## Project Structure

```
.
├── app/
│   ├── main.py              # FastAPI server — all webhook & admin handlers
│   ├── config.py            # Settings (pydantic-settings + .env)
│   ├── vapi_client.py       # Vapi REST client + assistant definition
│   ├── twilio_client.py     # Twilio conference & call management
│   └── appointment_store.py # In-memory scheduler (replace with EHR API)
├── scripts/
│   ├── setup_assistant.py   # One-time: create Vapi assistant
│   └── setup_phone.py       # One-time: import Twilio number to Vapi
├── requirements.txt
└── .env.example
```

---

## Customization

### Connect to a real EHR / scheduling system
Replace the functions in `app/appointment_store.py` with API calls to your EHR:
- **Athena Health** — use the AthenaNet REST API
- **Epic** — use Epic's FHIR R4 API
- **Jane App** — use the Jane API
- **Google Calendar** — use the Calendar API for simple scheduling

### Add providers / appointment types
Edit `PROVIDERS` and `APPOINTMENT_TYPES` in `app/appointment_store.py`, or pull them dynamically from your EHR.

### Change the AI voice
Update the `voice` block in `app/vapi_client.py`. ElevenLabs voices: `rachel`, `adam`, `bella`, `elli`. Or switch provider to `azure`, `google`, or `deepgram`.

### After-hours handling
Add a startup check in `app/main.py` that detects after-hours calls and plays a custom message or routes to `AFTER_HOURS_NUMBER`.

### Add SMS confirmations
After booking, use the Twilio SMS API to text the patient a confirmation with their appointment details.

---

## Production Checklist

- [ ] Replace `appointment_store.py` with calls to your EHR API
- [ ] Store messages and refill requests in an encrypted HIPAA-compliant database
- [ ] Add authentication to all `/admin/*` endpoints
- [ ] Validate `x-vapi-secret` header on all `/vapi/*` webhooks
- [ ] Use Redis for `_active_calls` state in `twilio_client.py`
- [ ] Enable TLS and deploy behind nginx or a managed platform (Railway, Fly.io, AWS)
- [ ] Implement SMS appointment reminders via Twilio
- [ ] Log all call activity to a HIPAA-compliant audit trail
- [ ] Obtain a Business Associate Agreement (BAA) from Vapi, Twilio, and Anthropic
