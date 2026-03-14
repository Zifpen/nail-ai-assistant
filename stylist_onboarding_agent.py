"""
AI Stylist Onboarding Agent

Conversational agent that helps stylists configure their services.
Collects service names and durations, then saves to the database via API.
"""

import os
import requests
import openai
from dotenv import load_dotenv
from datetime import datetime
load_dotenv()

# Set your OpenAI API key (use environment variable for security)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("Please set the OPENAI_API_KEY environment variable.")

openai.api_key = OPENAI_API_KEY

# Backend API base URL
API_BASE = "http://127.0.0.1:8000"

# -------------------------------
# API Integration
# -------------------------------

def save_stylist_services(stylist_id: int, services: list):
    """
    Save stylist services via API.
    
    Args:
        stylist_id (int): The stylist's ID
        services (list): List of dicts with 'name' and 'duration'
    """
    payload = {
        "stylist_id": stylist_id,
        "services": services
    }
    resp = requests.post(f"{API_BASE}/stylist/onboarding/services", json=payload)
    resp.raise_for_status()
    return resp.json()

# -------------------------------
# System Prompt
# -------------------------------

SYSTEM_PROMPT = """
You are an AI assistant helping stylists onboard to a nail salon booking system.

Your job is to:
* Welcome the stylist and explain the process
* Ask what services they offer
* For each service, ask how long it typically takes
* Collect all service names and durations
* When you have all the information, call the save_stylist_services function

Be friendly and conversational. Ask follow-up questions if information is missing.
Once you have collected all services and their durations, save the data.

Example conversation:
AI: Welcome! Let's set up the services you offer. What services do you provide?
Stylist: I do gel manicure and hard gel.
AI: Great! How long does a gel manicure usually take you?
Stylist: About 60 minutes.
AI: And how long for hard gel?
Stylist: 90 minutes.
AI: Perfect! I've saved your services.
"""

# -------------------------------
# Conversation Loop
# -------------------------------

def run_stylist_onboarding(stylist_id: int):
    """
    Main conversation loop for stylist onboarding.
    
    Args:
        stylist_id (int): The ID of the stylist being onboarded
    """
    print("Welcome to the Nail Salon Stylist Onboarding!")
    print("Type 'exit' to quit.\n")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ]

    collected_services = []

    while True:
        user_input = input("Stylist: ").strip()
        if user_input.lower() in {"exit", "quit"}:
            print("Goodbye!")
            break

        messages.append({"role": "user", "content": user_input})

        # Send to OpenAI
        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "save_stylist_services",
                        "description": "Save the collected services for the stylist",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "stylist_id": {"type": "integer"},
                                "services": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "name": {"type": "string"},
                                            "duration": {"type": "integer"}
                                        },
                                        "required": ["name", "duration"]
                                    }
                                }
                            },
                            "required": ["stylist_id", "services"]
                        }
                    }
                }
            ],
            tool_choice="auto"
        )

        msg = response.choices[0].message

        # If the LLM wants to call a tool
        if msg.tool_calls:
            for tool_call in msg.tool_calls:
                if tool_call.function.name == "save_stylist_services":
                    args = tool_call.function.arguments
                    import json
                    tool_args = json.loads(args)
                    # Override stylist_id to ensure it's correct
                    tool_args["stylist_id"] = stylist_id
                    result = save_stylist_services(**tool_args)
                    print(f"AI: {result['message']}")
                    return  # End onboarding after saving

        else:
            # No tool call, just respond
            print(f"AI: {msg.content}")

        messages.append({"role": "assistant", "content": msg.content})

if __name__ == "__main__":
    # For testing, use a stylist ID (in production, get from authentication)
    stylist_id = int(input("Enter stylist ID: "))
    run_stylist_onboarding(stylist_id)