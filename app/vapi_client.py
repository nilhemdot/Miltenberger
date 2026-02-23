"""Vapi API client for managing assistants, phone numbers, and calls."""

import httpx
from app.config import settings

VAPI_BASE_URL = "https://api.vapi.ai"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.vapi_api_key}",
        "Content-Type": "application/json",
    }


def create_assistant(name: str | None = None) -> dict:
    """Create the AI receptionist assistant in Vapi using Claude as the LLM."""
    business = settings.business_name
    hours = settings.business_hours
    assistant_name = name or f"{business} Receptionist"

    system_prompt = f"""You are a professional AI receptionist for {business}.

Your responsibilities:
- Greet callers warmly and professionally
- Determine the purpose of their call
- Answer common questions about {business} (hours, location, services)
- Schedule appointments or take messages when needed
- Transfer callers to the appropriate human agent when requested or required
- Handle difficult situations calmly and empathetically

Business hours: {hours}

Guidelines:
- Always be polite, concise, and helpful
- If you cannot answer a question, offer to take a message or transfer to a human agent
- Do not make up information — say "I don't have that information, let me connect you with someone who can help"
- Keep responses brief and conversational for a phone call context
- Confirm important details (names, phone numbers, appointment times) by reading them back

When a caller wants to speak with a human agent, use the transfer_to_agent function.
When a caller wants to leave a message, use the take_message function."""

    payload = {
        "name": assistant_name,
        "model": {
            "provider": "anthropic",
            "model": "claude-opus-4-6",
            "messages": [
                {"role": "system", "content": system_prompt}
            ],
            "temperature": 0.7,
            "maxTokens": 500,
        },
        "voice": {
            "provider": "11labs",
            "voiceId": "rachel",  # Professional female voice
            "stability": 0.5,
            "similarityBoost": 0.75,
        },
        "firstMessage": (
            f"Thank you for calling {business}. "
            "I'm your AI receptionist. How can I help you today?"
        ),
        "endCallMessage": (
            "Thank you for calling. Have a wonderful day. Goodbye!"
        ),
        "endCallPhrases": [
            "goodbye",
            "bye",
            "thank you bye",
            "that's all",
            "hang up",
        ],
        "transcriber": {
            "provider": "deepgram",
            "model": "nova-2",
            "language": "en-US",
        },
        "serverUrl": f"{settings.server_base_url}/vapi/webhook",
        "serverUrlSecret": settings.vapi_api_key[:16],  # Use first 16 chars as webhook secret
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "transfer_to_agent",
                    "description": (
                        "Transfer the caller to a human agent. "
                        "Use this when the caller requests to speak with a human, "
                        "or when you cannot resolve their issue."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "reason": {
                                "type": "string",
                                "description": "Brief reason for the transfer",
                            }
                        },
                        "required": ["reason"],
                    },
                },
                "server": {
                    "url": f"{settings.server_base_url}/vapi/tool/transfer",
                    "secret": settings.vapi_api_key[:16],
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "take_message",
                    "description": (
                        "Record a message from the caller when a human agent "
                        "is unavailable or when the caller wants to leave a message."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "caller_name": {
                                "type": "string",
                                "description": "Full name of the caller",
                            },
                            "caller_phone": {
                                "type": "string",
                                "description": "Callback phone number",
                            },
                            "message": {
                                "type": "string",
                                "description": "The message content",
                            },
                        },
                        "required": ["caller_name", "message"],
                    },
                },
                "server": {
                    "url": f"{settings.server_base_url}/vapi/tool/message",
                    "secret": settings.vapi_api_key[:16],
                },
            },
        ],
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
        "name": f"{settings.business_name} Line",
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
    """Initiate an outbound call using the AI receptionist."""
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
    """Retrieve details for a specific call."""
    with httpx.Client() as client:
        response = client.get(
            f"{VAPI_BASE_URL}/call/{call_id}",
            headers=_headers(),
        )
        response.raise_for_status()
        return response.json()


def list_calls(limit: int = 20) -> list[dict]:
    """List recent calls."""
    with httpx.Client() as client:
        response = client.get(
            f"{VAPI_BASE_URL}/call",
            headers=_headers(),
            params={"limit": limit},
        )
        response.raise_for_status()
        return response.json()
