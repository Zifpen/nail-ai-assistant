"""
LLM-powered AI Booking Agent for Nail Salon

This agent uses the OpenAI API with tool calling to interact with users,
retrieve available slots, and book appointments via the FastAPI backend.

Tools:
- get_available_slots: GET /available-slots
- book_appointment: POST /book

System prompt ensures the agent never invents times and always checks availability.
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

# Current date and time for natural language interpretation
today = datetime.now().strftime("%Y-%m-%d")
current_time = datetime.now().strftime("%H:%M")

# -------------------------------
# Tool Definitions
# -------------------------------

def get_available_slots(date: str, service_duration: int):
    """
    Call the backend API to get available slots.
    """
    params = {"date": date, "service_duration": service_duration}
    resp = requests.get(f"{API_BASE}/available-slots", params=params)
    resp.raise_for_status()
    return resp.json()

def book_appointment(client_name, service_name, start_time, end_time, service_duration, date):
    """
    Call the backend API to book an appointment.
    Ensures time format is 'YYYY-MM-DD HH:MM'.
    """
    from datetime import datetime
    def to_required_format(dt_str):
        # Remove 'T' if present and split off seconds if present
        dt_str = dt_str.replace('T', ' ')
        if len(dt_str) > 16:
            dt_str = dt_str[:16]
        # Try parsing to ensure it's valid
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(dt_str, fmt)
                return dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                continue
        return dt_str  # fallback

    start_time_fmt = to_required_format(str(start_time))
    end_time_fmt = to_required_format(str(end_time))

    payload = {
        "client_name": client_name,
        "service_name": service_name,
        "start_time": start_time_fmt,
        "end_time": end_time_fmt,
        "service_duration": service_duration,
        "date": date
    }
    print("Booking payload:", payload)  # Debug print
    resp = requests.post(f"{API_BASE}/book", json=payload)
    if resp.status_code != 200:
        print("Error response from /book:", resp.text)  # Debug print
    resp.raise_for_status()
    return resp.json()

# Tool schema for OpenAI tool calling
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_available_slots",
            "description": "Retrieve available booking time slots.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Date in YYYY-MM-DD format"},
                    "service_duration": {"type": "integer", "description": "Service duration in minutes"}
                },
                "required": ["date", "service_duration"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "book_appointment",
            "description": "Create a booking.",
            "parameters": {
                "type": "object",
                "properties": {
                    "client_name": {"type": "string"},
                    "service_name": {"type": "string"},
                    "start_time": {"type": "string"},
                    "end_time": {"type": "string"},
                    "service_duration": {"type": "integer"},
                    "date": {"type": "string"}
                },
                "required": ["client_name", "service_name", "start_time", "end_time", "service_duration", "date"]
            }
        }
    }
]

# -------------------------------
# System Prompt
# -------------------------------

SYSTEM_PROMPT = f"""
You are an AI assistant for a nail salon.

Your job is to:
* help customers find available time slots
* help customers book appointments
* ask follow-up questions if information is missing
* call tools when scheduling actions are required

Never invent appointment times.
Always call get_available_slots before suggesting times.

Current date: {today}
Current time: {current_time}

Time Interpretation Rules:
1. Always interpret natural language time expressions relative to today's date ({today}).
2. Convert them into explicit calendar dates using the format: YYYY-MM-DD.
3. Never assume past years. Always use the current year unless the user explicitly specifies another year.
4. For time-of-day expressions, use these ranges:
   - morning: 09:00 – 12:00
   - afternoon: 12:00 – 17:00
   - evening: 17:00 – 20:00
5. If a user specifies a time range such as "tomorrow afternoon", filter available slots so they fall within that range.
6. For relative dates:
   - today: {today}
   - tomorrow: the day after {today}
   - next Monday: the next Monday after {today}
   - next week: 7 days from {today}
"""

# -------------------------------
# Conversation Loop
# -------------------------------

def run_agent():
    """
    Main conversation loop for the AI agent.
    """
    print("Welcome to the Nail Salon AI Assistant!")
    print("Type 'exit' to quit.\n")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ]

    while True:
        user_input = input("User: ").strip()
        if user_input.lower() in {"exit", "quit"}:
            print("Goodbye!")
            break

        messages.append({"role": "user", "content": user_input})

        # Send to OpenAI with tool calling enabled
        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=TOOLS,
            tool_choice="auto"
        )

        msg = response.choices[0].message

        # If the LLM wants to call a tool
        if msg.tool_calls:
            tool_outputs = []
            for tool_call in msg.tool_calls:
                name = tool_call.function.name
                args = tool_call.function.arguments

                # Parse arguments
                import json
                tool_args = json.loads(args)

                # Call the appropriate tool
                if name == "get_available_slots":
                    result = get_available_slots(**tool_args)
                elif name == "book_appointment":
                    result = book_appointment(**tool_args)
                else:
                    result = {"error": f"Unknown tool: {name}"}

                tool_outputs.append({
                    "tool_call_id": tool_call.id,
                    "output": result
                })

            # Add tool outputs to messages and continue the conversation
            messages.append(msg)
            for tool_output in tool_outputs:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_output["tool_call_id"],
                    "content": str(tool_output["output"])
                })

            # Get the final response from the LLM
            final_response = openai.chat.completions.create(
                model="gpt-4-1106-preview",
                messages=messages
            )
            final_msg = final_response.choices[0].message
            print(f"Assistant: {final_msg.content}")
            messages.append({"role": "assistant", "content": final_msg.content})

        else:
            # No tool call, just respond
            print(f"Assistant: {msg.content}")
            messages.append({"role": "assistant", "content": msg.content})

if __name__ == "__main__":
    run_agent()