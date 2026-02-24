from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Vapi
    vapi_api_key: str
    vapi_assistant_id: str = ""
    vapi_phone_number_id: str = ""
    vapi_reminder_assistant_id: str = ""   # Optional dedicated reminder assistant

    # Twilio
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_phone_number: str

    # Anthropic
    anthropic_api_key: str = ""

    # Server
    server_base_url: str = "http://localhost:8000"
    port: int = 8000

    # Practice information
    business_name: str = "Family Medical Practice"
    business_hours: str = "Monday through Friday, 8 AM to 5 PM"
    office_address: str = "123 Health Street, Suite 100, Your City, ST 00000"
    providers: str = "Dr. Smith, Dr. Johnson, Dr. Patel"
    office_timezone: str = "America/New_York"
    office_open_time: str = "08:00"    # 24h HH:MM
    office_close_time: str = "17:00"   # 24h HH:MM

    # Transfer / routing numbers
    human_agent_number: str = ""       # Front desk / operator direct line
    nurse_line_number: str = ""        # Clinical nurse triage line
    billing_line_number: str = ""      # Billing department direct line
    after_hours_number: str = ""       # On-call / answering service

    # Patient-facing URLs (sent via SMS)
    intake_form_url: str = ""          # New patient intake form URL
    patient_portal_url: str = ""       # Patient portal URL for lab results, etc.

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
