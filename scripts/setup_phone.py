#!/usr/bin/env python3
"""
Import your Twilio phone number into Vapi and assign the AI receptionist.

Prerequisites:
  1. Run scripts/setup_assistant.py first and set VAPI_ASSISTANT_ID in .env
  2. Ensure TWILIO_PHONE_NUMBER, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN are set

Run:
    python scripts/setup_phone.py

Then add the printed VAPI_PHONE_NUMBER_ID to your .env file.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

from app.vapi_client import import_twilio_number
from app.config import settings


def main():
    if not settings.vapi_assistant_id:
        print("ERROR: VAPI_ASSISTANT_ID is not set in .env")
        print("Run scripts/setup_assistant.py first.")
        sys.exit(1)

    print(f"Importing Twilio number {settings.twilio_phone_number} into Vapi...")
    print(f"Assigning assistant: {settings.vapi_assistant_id}\n")

    phone = import_twilio_number(settings.vapi_assistant_id)

    phone_number_id = phone.get("id", "")
    print("✓ Phone number imported successfully!")
    print(f"  Number: {phone.get('number', settings.twilio_phone_number)}")
    print(f"  ID:     {phone_number_id}")
    print(f"\nAdd this to your .env file:")
    print(f"  VAPI_PHONE_NUMBER_ID={phone_number_id}")
    print(f"\nIncoming calls to {settings.twilio_phone_number} will now be")
    print(f"answered by your AI receptionist.")


if __name__ == "__main__":
    main()
