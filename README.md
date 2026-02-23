# AI Receptionist — Vapi + Twilio + Claude

An AI-powered phone receptionist that answers inbound calls, takes messages, and transfers callers to human agents. Built with **Vapi** (voice AI), **Twilio** (telephony), and **Claude** (LLM via Anthropic).

## Architecture

```
Incoming call → Twilio number → Vapi AI Assistant (Claude)
                                    ↓
                         ┌──────────────────────┐
                         │  FastAPI Webhook Server │
                         └──────────────────────┘
                              ↓           ↓
                     Transfer to       Take a
                     human agent       message
                         ↓
                  Twilio Conference Room
                         ↓
                   Human Agent Line
```

## Features

- **AI receptionist** powered by Claude (claude-opus-4-6) via Vapi
- **Inbound call handling** — answers calls 24/7 with a natural voice
- **Call transfer** — connects callers to a human agent via Twilio conference
- **Voicemail fallback** — records a message if no agent is available
- **Message taking** — AI collects caller name, number, and message
- **Admin API** — view messages, trigger outbound calls, list recent calls

## Prerequisites

- [Vapi account](https://vapi.ai) with API key
- [Twilio account](https://twilio.com) with a phone number
- [Anthropic API key](https://console.anthropic.com) (for Claude)
- Python 3.11+
- A public HTTPS URL (e.g. [ngrok](https://ngrok.com) for local dev)

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your actual credentials
```

Required variables:

| Variable | Description |
|---|---|
| `VAPI_API_KEY` | Vapi dashboard API key |
| `TWILIO_ACCOUNT_SID` | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | Twilio auth token |
| `TWILIO_PHONE_NUMBER` | Your Twilio number (E.164 format) |
| `ANTHROPIC_API_KEY` | Anthropic API key (used by Vapi) |
| `SERVER_BASE_URL` | Public HTTPS URL of this server |
| `BUSINESS_NAME` | Your business name |
| `BUSINESS_HOURS` | Business hours (shown in system prompt) |
| `HUMAN_AGENT_NUMBER` | Number to transfer calls to (optional) |

### 3. Start the server

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

For local development, expose it with ngrok:

```bash
ngrok http 8000
# Copy the https URL to SERVER_BASE_URL in .env
```

### 4. Create the Vapi assistant

```bash
python scripts/setup_assistant.py
# Copy the printed VAPI_ASSISTANT_ID to .env
```

### 5. Import your Twilio number into Vapi

```bash
python scripts/setup_phone.py
# Copy the printed VAPI_PHONE_NUMBER_ID to .env
```

Your AI receptionist is now live. Call your Twilio number to test it.

## API Endpoints

### Vapi Webhooks (called by Vapi)
| Method | Path | Description |
|---|---|---|
| `POST` | `/vapi/webhook` | Assistant lifecycle events |
| `POST` | `/vapi/tool/transfer` | Transfer caller to human agent |
| `POST` | `/vapi/tool/message` | Record a message from caller |

### Twilio Webhooks (called by Twilio)
| Method | Path | Description |
|---|---|---|
| `POST` | `/twilio/conference` | Join conference room (TwiML) |
| `POST` | `/twilio/agent-status` | Agent call status callback |
| `POST` | `/twilio/unavailable` | Agent unavailable TwiML |
| `POST` | `/twilio/voicemail` | Receive voicemail recording |

### Admin API
| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/admin/messages` | View all messages & voicemails |
| `POST` | `/admin/call` | Make outbound call `{"to": "+1..."}` |
| `GET` | `/admin/calls` | List recent calls from Vapi |

## Project Structure

```
.
├── app/
│   ├── main.py          # FastAPI server — all webhook handlers
│   ├── config.py        # Settings via pydantic-settings
│   ├── vapi_client.py   # Vapi REST API client
│   └── twilio_client.py # Twilio call management
├── scripts/
│   ├── setup_assistant.py  # One-time: create Vapi assistant
│   └── setup_phone.py      # One-time: import Twilio number to Vapi
├── requirements.txt
└── .env.example
```

## Customization

### Change the AI model
In `app/vapi_client.py`, update the `model` block inside `create_assistant()`:
```python
"model": {
    "provider": "anthropic",
    "model": "claude-opus-4-6",  # or claude-sonnet-4-6, claude-haiku-4-5
    ...
}
```

### Change the voice
Update the `voice` block in `create_assistant()`. Available ElevenLabs voices include `rachel`, `adam`, `bella`, `elli`, and others from your ElevenLabs account.

### Add more tools
Add entries to the `tools` list in `create_assistant()` and create corresponding `@app.post("/vapi/tool/<name>")` handlers in `app/main.py`.

### Persist messages to a database
Replace `messages_log` in `app/main.py` with a database (SQLite, PostgreSQL, etc.) for production use.

## Production Notes

- Use a proper database instead of the in-memory `messages_log`
- Use Redis or a database for `_active_calls` in `twilio_client.py`
- Add authentication to `/admin/*` endpoints
- Validate the `x-vapi-secret` header on all `/vapi/*` endpoints
- Deploy behind a reverse proxy (nginx) with TLS termination
