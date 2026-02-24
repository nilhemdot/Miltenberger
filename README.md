# Doctor's Office AI Receptionist — Vapi + Twilio + Claude

A full-featured AI phone receptionist for medical practices. Built with **Claude** (LLM via Vapi), **Twilio** (telephony + SMS), and **FastAPI** (webhook server).

> **HIPAA Notice:** For production deployments, all patient data must be stored in an encrypted, access-controlled system compliant with HIPAA's Technical Safeguards (45 CFR § 164.312). Replace the in-memory stores with a compliant database and integrate with your EHR (e.g. Epic, Athena Health). Obtain Business Associate Agreements (BAAs) from Vapi, Twilio, and Anthropic before handling PHI.

---

## Features

### Scheduling
| Capability | Details |
|---|---|
| **Check availability** | Next 5 business days, all providers or filtered |
| **Schedule appointment** | Books slot, sends SMS confirmation, fires intake form link for new patients |
| **Reschedule** | Finds existing appt by name/DOB, moves to new slot, sends updated SMS |
| **Cancel** | Cancels with reason, notifies patient by SMS, auto-notifies waitlisted patients |
| **Waitlist** | Adds patient to waitlist; texts them automatically when a matching slot opens |

### Clinical Support
| Capability | Details |
|---|---|
| **Prescription refills** | Logs refill request; automatically blocks controlled substances |
| **Transfer to nurse** | Live Twilio conference transfer for clinical questions |
| **Messages for care team** | Urgency-flagged (routine / same-day / urgent) with callback ETA |
| **Emergency detection** | Instructs patient to call 911 for emergency symptoms immediately |
| **Post-visit follow-up** | Automated SMS 24h after appointment (via APScheduler) |
| **Lab results notification** | Staff triggers SMS to patient when results are ready |

### Billing & Admin
| Capability | Details |
|---|---|
| **Billing questions** | Logs question + callback; optional live transfer to billing line |
| **Insurance collection** | Collects primary/secondary insurance during new patient scheduling |
| **Refill approval** | Staff approves refill via API → patient gets SMS confirmation |
| **Insurance verification** | Staff marks insurance as verified via API |

### Automation (APScheduler)
| Job | Schedule | What it does |
|---|---|---|
| SMS reminders | Daily 8:00 AM | Texts patients about tomorrow's appointments |
| Reminder calls | Daily 8:15 AM | Vapi outbound AI call for tomorrow's appointments |
| Follow-up SMS | Daily 9:00 AM | Post-visit check-in for yesterday's visits |
| Waitlist reset | Every 30 min | Re-opens waitlist offers that expired (2h timeout) |

### Accessibility
| Capability | Details |
|---|---|
| **Multi-language** | Deepgram `multi` transcription; Claude responds in patient's language |
| **After-hours routing** | Outside business hours: transfers to on-call line or records voicemail |
| **Voicemail fallback** | Nurse/agent no-answer → voicemail recording |

---

## Architecture

```
Patient calls Twilio number
        ↓
After-hours check (middleware)
   ├─ After hours → Transfer to on-call OR voicemail
   └─ Business hours ↓
        ↓
Vapi answers → Claude AI Receptionist (multilingual)
        ↓ (tool calls)
┌───────────────────────────────────────────────────────────┐
│  FastAPI Webhook Server                                    │
│                                                           │
│  check_availability    → appointment_store                │
│  schedule_appointment  → appointment_store + SMS confirm  │
│  find_appointment      → appointment_store                │
│  reschedule_appointment→ appointment_store + SMS update   │
│  cancel_appointment    → appointment_store + SMS + waitlist│
│  add_to_waitlist       → waitlist store                   │
│  request_refill        → refill log + controlled filter   │
│  collect_insurance     → insurance store                  │
│  take_message          → messages log (urgency-flagged)   │
│  billing_question      → messages log + optional transfer │
│  transfer_to_nurse     → Twilio conference bridge         │
└───────────────────────────────────────────────────────────┘
        ↓ (APScheduler — background)
SMS reminders, outbound reminder calls, post-visit follow-ups
```

---

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure environment
```bash
cp .env.example .env
# Edit .env — fill in all credentials and practice details
```

### 3. Start the server
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

For local dev, expose with ngrok:
```bash
ngrok http 8000
# Paste the https URL into SERVER_BASE_URL in .env
```

### 4. Create the Vapi assistant (one-time)
```bash
python scripts/setup_assistant.py
# Copy VAPI_ASSISTANT_ID to .env
```

### 5. Import your Twilio number into Vapi (one-time)
```bash
python scripts/setup_phone.py
# Copy VAPI_PHONE_NUMBER_ID to .env
```

---

## API Reference

### Vapi Tool Webhooks
| Path | Tool |
|---|---|
| `POST /vapi/tool/availability` | `check_availability` |
| `POST /vapi/tool/schedule` | `schedule_appointment` |
| `POST /vapi/tool/find-appointment` | `find_appointment` |
| `POST /vapi/tool/reschedule` | `reschedule_appointment` |
| `POST /vapi/tool/cancel` | `cancel_appointment` |
| `POST /vapi/tool/waitlist` | `add_to_waitlist` |
| `POST /vapi/tool/refill` | `request_prescription_refill` |
| `POST /vapi/tool/collect-insurance` | `collect_insurance_info` |
| `POST /vapi/tool/message` | `take_message` |
| `POST /vapi/tool/billing` | `billing_question` |
| `POST /vapi/tool/transfer-nurse` | `transfer_to_nurse` |

### Twilio Webhooks
| Path | Description |
|---|---|
| `POST /twilio/inbound` | Entry point (after-hours middleware applied) |
| `POST /twilio/conference` | Join conference room (TwiML) |
| `POST /twilio/agent-status` | Agent/nurse call status callback |
| `POST /twilio/unavailable` | No-answer fallback TwiML |
| `POST /twilio/voicemail` | Voicemail recording receipt |

### Admin / Staff API
| Path | Description |
|---|---|
| `GET /health` | Health + live stats |
| `GET /admin/appointments?date=YYYY-MM-DD` | List appointments |
| `GET /admin/messages` | Messages, voicemails, nurse flags, billing questions |
| `GET /admin/refills` | Refill requests |
| `PATCH /admin/refills/{idx}/approve` | Approve refill → SMS patient |
| `GET /admin/waitlist` | Waitlist entries |
| `DELETE /admin/waitlist/{id}` | Remove from waitlist |
| `GET /admin/insurance` | Unverified insurance records |
| `PATCH /admin/insurance/verify` | Mark insurance as verified |
| `POST /admin/lab-results` | Notify patient lab results ready |
| `POST /admin/call` | Trigger outbound AI call |
| `GET /admin/calls` | Recent Vapi call history |
| `GET /admin/scheduler/jobs` | Scheduled job next run times |

---

## Project Structure

```
.
├── app/
│   ├── main.py              # FastAPI server — all webhooks, middleware, admin API
│   ├── config.py            # Settings (pydantic-settings + .env)
│   ├── vapi_client.py       # Vapi REST client + 11-tool assistant definition
│   ├── twilio_client.py     # Twilio conference & call management
│   ├── appointment_store.py # Scheduling (replace with EHR API in production)
│   ├── waitlist.py          # Waitlist management
│   ├── insurance.py         # Insurance info store
│   ├── sms.py               # Twilio SMS helpers
│   ├── scheduler.py         # APScheduler background jobs
│   └── after_hours.py       # Business hours detection + routing TwiML
├── scripts/
│   ├── setup_assistant.py   # One-time: create Vapi assistant
│   └── setup_phone.py       # One-time: import Twilio number to Vapi
├── requirements.txt
└── .env.example
```

---

## Production Checklist

- [ ] Replace `appointment_store.py` with your EHR API (Epic FHIR, Athena, etc.)
- [ ] Persist `messages_log`, `refill_requests`, `waitlist`, `insurance` in an encrypted database
- [ ] Use Redis for `_active_calls` in `twilio_client.py`
- [ ] Add authentication to all `/admin/*` endpoints
- [ ] Validate `x-vapi-secret` header on all `/vapi/*` webhooks
- [ ] Configure `INTAKE_FORM_URL` and `PATIENT_PORTAL_URL` for patient SMS links
- [ ] Set `OFFICE_TIMEZONE`, `OFFICE_OPEN_TIME`, `OFFICE_CLOSE_TIME` for accurate after-hours routing
- [ ] Set `AFTER_HOURS_NUMBER` for on-call routing, or leave blank for voicemail
- [ ] Set `BILLING_LINE_NUMBER` and `NURSE_LINE_NUMBER` for live transfers
- [ ] Obtain BAAs from Vapi, Twilio, and Anthropic
- [ ] Deploy behind TLS (nginx, Fly.io, Railway, AWS App Runner, etc.)
- [ ] Implement HIPAA-compliant audit logging for all PHI access
