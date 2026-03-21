"""
AI Stylist Onboarding Agent

Conversational agent that helps stylists configure their services.
Collects service names and durations, then saves to the database via API.
"""

import os
import requests
import openai
import bcrypt
from dotenv import load_dotenv
from datetime import datetime
from database import (
    create_stylist_profile,
    create_stylist_service,
    get_stylist_by_phone as get_stylist_by_phone_local,
    get_user_by_phone,
    init_database,
    insert_user,
    update_stylist_profile as update_stylist_profile_local,
)
from service_resolver import resolve_service_name
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
    try:
        resp = requests.post(f"{API_BASE}/stylist/onboarding/services", json=payload)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        services_added = 0
        for service in services:
            resolved = resolve_service_name(service["name"])
            create_stylist_service(
                stylist_id=stylist_id,
                service_id=resolved["service_id"],
                duration=service["duration"],
            )
            services_added += 1
        return {
            "message": f"Successfully onboarded {services_added} services for stylist {stylist_id}",
            "services_added": services_added,
        }


def save_stylist_profile(stylist_id: int, bio: str, experience_years: int):
    """Save stylist profile data via API."""
    payload = {
        "stylist_id": stylist_id,
        "bio": bio,
        "experience_years": experience_years,
    }
    try:
        resp = requests.post(f"{API_BASE}/stylist/onboarding/profile", json=payload)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        update_stylist_profile_local(
            stylist_id=stylist_id,
            bio=bio,
            experience_years=experience_years,
        )
        return {
            "message": f"Successfully updated profile for stylist {stylist_id}",
            "stylist_id": stylist_id,
        }


def find_stylist_by_phone(phone: str):
    """Look up an existing stylist profile by phone number."""
    try:
        resp = requests.get(f"{API_BASE}/stylists/by-phone/{phone}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        stylist = get_stylist_by_phone_local(phone)
        return stylist or None


def register_stylist(name: str, phone: str, password: str):
    """Register a new stylist user and create the linked stylist profile."""
    payload = {
        "name": name,
        "phone": phone,
        "password": password,
        "role": "stylist",
    }
    try:
        resp = requests.post(f"{API_BASE}/register", json=payload)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        existing_user = get_user_by_phone(phone)
        if existing_user:
            if existing_user.get("role") != "stylist":
                raise ValueError("That phone number is already registered to a non-stylist account.")
            existing_stylist = get_stylist_by_phone_local(phone)
            if existing_stylist:
                return {
                    "user_id": existing_user["id"],
                    "message": f"User {existing_user['name']} already registered as stylist",
                }
            create_stylist_profile(existing_user["id"])
            return {
                "user_id": existing_user["id"],
                "message": f"User {existing_user['name']} already registered as stylist",
            }

        password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        user_id = insert_user(
            name=name,
            phone=phone,
            password_hash=password_hash,
            role="stylist",
        )
        create_stylist_profile(user_id)
        return {
            "user_id": user_id,
            "message": f"User {name} registered successfully as stylist",
        }

# -------------------------------
# System Prompt
# -------------------------------

SYSTEM_PROMPT = """
You are an AI assistant helping stylists onboard to a nail salon booking system.

Your job is to:
* Welcome the stylist and explain the service setup process
* Ask what services they offer
* For each service, ask how long it typically takes
* Collect all service names and durations
* When you have all the information, call the save_stylist_services function

Be friendly and conversational. Ask follow-up questions if information is missing.
The stylist profile is already saved before this conversation starts, so do not ask again for bio or years of experience.
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
    print("AI: Let's set up your profile first. Please share a short bio for customers.")
    bio = input("Stylist: ").strip()
    if bio.lower() in {"exit", "quit"}:
        print("Goodbye!")
        return

    print("AI: How many years of experience would you like on your profile?")
    raw_experience = input("Stylist: ").strip()
    if raw_experience.lower() in {"exit", "quit"}:
        print("Goodbye!")
        return
    try:
        experience_years = max(0, int(raw_experience))
    except ValueError:
        experience_years = 0

    profile_result = save_stylist_profile(
        stylist_id=stylist_id,
        bio=bio,
        experience_years=experience_years,
    )
    print(f"AI: {profile_result['message']}")
    print("AI: Great. Now let's set up the services you offer.")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "assistant",
            "content": (
                f"The profile has already been saved with bio: {bio} "
                f"and experience: {experience_years} years. "
                "Only collect the services offered and the duration for each service."
            ),
        },
    ]

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

def run_stylist_onboarding_flow():
    """Start stylist onboarding from phone lookup instead of manual stylist_id entry."""
    init_database()
    print("Welcome to the Nail Salon Stylist Onboarding!")
    print("Type 'exit' to quit.\n")

    phone = input("Stylist phone: ").strip()
    if phone.lower() in {"exit", "quit"}:
        print("Goodbye!")
        return

    stylist = find_stylist_by_phone(phone)
    if stylist:
        stylist_id = stylist["id"]
        print(f"AI: Welcome back, {stylist['name']}. I found your stylist profile.")
    else:
        print("AI: I don't see a stylist profile for that phone number yet. Let's create one.")
        print("AI: What name should I use for your stylist profile?")
        name = input("Stylist: ").strip()
        if name.lower() in {"exit", "quit"}:
            print("Goodbye!")
            return

        print("AI: Please choose a password for your stylist account.")
        password = input("Stylist: ").strip()
        if password.lower() in {"exit", "quit"}:
            print("Goodbye!")
            return

        register_stylist(name=name, phone=phone, password=password)
        stylist = find_stylist_by_phone(phone)
        if not stylist:
            raise RuntimeError("Stylist registration succeeded but stylist lookup failed")
        stylist_id = stylist["id"]
        print(f"AI: Perfect. Your stylist account is ready, {stylist['name']}.")

    run_stylist_onboarding(stylist_id)


if __name__ == "__main__":
    run_stylist_onboarding_flow()
