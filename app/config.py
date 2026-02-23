from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Vapi
    vapi_api_key: str
    vapi_assistant_id: str = ""
    vapi_phone_number_id: str = ""

    # Twilio
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_phone_number: str

    # Anthropic
    anthropic_api_key: str = ""

    # Server
    server_base_url: str = "http://localhost:8000"
    port: int = 8000

    # Receptionist
    business_name: str = "Acme Corporation"
    business_hours: str = "Monday through Friday, 9 AM to 5 PM Pacific"
    human_agent_number: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
