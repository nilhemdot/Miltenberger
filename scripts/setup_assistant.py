#!/usr/bin/env python3
"""
Create the Vapi AI receptionist assistant.

Run this once to create the assistant and get its ID:
    python scripts/setup_assistant.py

Then add the printed VAPI_ASSISTANT_ID to your .env file.
"""

import os
import sys

# Allow running from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

from app.vapi_client import create_assistant
from app.config import settings


def main():
    print(f"Creating AI receptionist for: {settings.business_name}")
    print(f"Server URL: {settings.server_base_url}")
    print(f"Model: Claude (claude-opus-4-6) via Anthropic\n")

    assistant = create_assistant()

    assistant_id = assistant.get("id", "")
    print("✓ Assistant created successfully!")
    print(f"  Name:  {assistant.get('name')}")
    print(f"  ID:    {assistant_id}")
    print(f"\nAdd this to your .env file:")
    print(f"  VAPI_ASSISTANT_ID={assistant_id}")


if __name__ == "__main__":
    main()
