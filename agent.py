"""
LLM-powered AI Booking Agent for Nail Salon

This agent uses a structured three-layer architecture:
1. Intent Layer: Analyzes user messages and detects intent
2. Planner: Generates action plans based on detected intents
3. Tool Executor: Executes tools in sequence

The agent combines structured planning with LLM-powered natural language responses.
"""




import os
import requests
import openai
from dotenv import load_dotenv
from datetime import datetime
from typing import Dict, Any
from agent.responses import (
    build_booking_confirmation,
    build_booking_error_response,
    build_services_response,
    build_stylists_response,
)
from agent.time_negotiation import (
    apply_time_bounds,
    apply_time_preference,
    build_display_slots,
    handle_slot_navigation,
    reset_time_selection,
    resolve_selected_slot,
)
from intent_layer import analyze_intent
from planner import create_plan
from tool_executor import execute_actions
from database import (
    get_client_by_phone,
    get_client_history,
    get_services_for_stylist,
    get_stylist_by_id,
    init_database,
    normalize_phone,
    upsert_client,
)
# --- Conversation Memory Integration ---
from agent.memory import load_context, update_context, reset_context, default_context
from logger import get_logger
load_dotenv()

logger = get_logger("agent")

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
# System Prompt (Simplified - now intent-driven)
# -------------------------------

SYSTEM_PROMPT = f"""
You are an AI assistant for a nail salon booking system.

Your role is to:
- Understand customer requests through natural conversation
- Provide helpful, friendly responses
- Guide customers through the booking process
- Answer questions about services and stylists

The system will automatically handle:
- Intent detection from your messages
- Action planning and execution
- Tool calling for data retrieval and booking

Current date: {today}
Current time: {current_time}

Be conversational and helpful. The technical aspects are handled by the system's intent layer.
"""

# -------------------------------
# Three-Layer Agent Architecture
# -------------------------------

class NailSalonAgent:
    """AI agent using structured three-layer architecture."""

    def __init__(self, client_profile: Dict[str, Any] | None = None):
        self.conversation_history = []
        self.system_prompt = SYSTEM_PROMPT
        self.client_profile = client_profile or {}

    def _user_wants_stylist_recommendation(self, user_message: str) -> bool:
        """Detect when the user wants a stylist recommendation."""
        message_lower = user_message.lower()
        recommendation_phrases = [
            "i have no idea",
            "no idea",
            "not sure",
            "i don't know",
            "any stylist",
            "whoever is available",
            "whoever's available",
            "anyone",
            "doesn't matter",
            "recommend",
            "can you recommend",
            "who do you recommend",
            "which stylist do you recommend",
        ]
        return any(phrase in message_lower for phrase in recommendation_phrases)

    def _build_stylist_recommendation(self, context: Dict[str, Any]) -> str | None:
        """Build a recommendation blurb from stylist bios without auto-selecting anyone."""
        stylists = context.get("available_stylists", [])
        service = (context.get("service_name") or context.get("service") or "").lower()
        service_id = context.get("service_id")
        if not stylists:
            return None

        ranked = []
        for stylist in stylists:
            score = 0
            reasons = []
            bio = (stylist.get("bio") or "").strip()
            bio_lower = bio.lower()
            experience = stylist.get("experience_years")
            service_matches = []

            if service_id:
                try:
                    service_matches = get_services_for_stylist(stylist["id"])
                except Exception:
                    service_matches = []

            matching_service = None
            for offered_service in service_matches:
                offered_name = (offered_service.get("name") or "").lower()
                offered_service_id = offered_service.get("service_id")
                if (service_id and offered_service_id == service_id) or (service and offered_name == service):
                    matching_service = offered_service
                    break

            if matching_service:
                score += 5
                reasons.append(f"offers {matching_service.get('name', context.get('service_name', 'this service'))}")

            if service and bio and service in bio_lower:
                score += 3
                reasons.append("their bio mentions this service")
            elif service and bio and any(word in bio_lower for word in service.split()):
                score += 2
                reasons.append("their bio overlaps with this service")

            if experience:
                score += min(int(experience), 10) / 10
                reasons.append(f"{experience} years of experience")

            if bio and not reasons:
                reasons.append(bio)

            ranked.append((score, stylist, reasons))

        ranked.sort(key=lambda item: (-item[0], item[1]["name"]))
        top_stylists = ranked[:2]
        suggestion_parts = []
        for _, stylist, reasons in top_stylists:
            reason_text = reasons[0] if reasons else "they look like a strong fit"
            suggestion_parts.append(f"{stylist['name']} ({reason_text})")

        if not suggestion_parts:
            return None

        return "Here are my suggestions: " + "; ".join(suggestion_parts) + ". Which stylist would you like?"

    def _handle_time_rejection(self, context: Dict[str, Any], user_message: str) -> bool:
        """Reset slot selection state when the user rejects the current set of times."""
        message_lower = user_message.lower()
        rejection_phrases = [
            "no time is good",
            "nothing works",
            "nothing works for me",
            "nothing fits",
            "none of these",
            "none of these work",
            "none of these work for me",
            "doesn't work",
            "doesnt work",
            "won't work",
            "wont work",
            "these don't work",
            "these dont work",
            "these won't work",
            "these wont work",
            "that doesn't work",
            "that doesnt work",
            "that won't work",
            "that wont work",
            "not good",
            "not available",
            "something else",
            "other day",
            "the other day",
            "maybe the other day",
            "different time",
            "different day",
            "another day",
            "no thanks",
            "nope",
        ]
        if not any(phrase in message_lower for phrase in rejection_phrases):
            return False

        reset_time_selection(context, reset_date=True)
        context["time_preference"] = None
        context["time_after"] = None
        context["time_before"] = None
        context["time_direction"] = None
        return True

    def _is_last_appointment_question(self, user_message: str) -> bool:
        """Detect questions about the client's previous appointment or stylist."""
        message_lower = user_message.lower()
        patterns = [
            "last appointment",
            "previous appointment",
            "last stylist",
            "previous stylist",
            "who did my nails last time",
            "who was my stylist last time",
            "who was my last stylist",
            "which stylist did i book last time",
            "which stylist i book last time",
            "what stylist did i book last time",
            "what stylist i book last time",
            "who did i book last time",
            "who did i book with last time",
            "who did i see last time",
            "上次预约",
            "上次是谁",
            "上次哪个stylist",
            "上次哪个美甲师",
        ]
        if any(pattern in message_lower for pattern in patterns):
            return True

        has_last_time = "last time" in message_lower or "previous" in message_lower
        asks_about_stylist = "stylist" in message_lower or "book with" in message_lower
        asks_about_who = "who" in message_lower and "book" in message_lower
        return has_last_time and (asks_about_stylist or asks_about_who)

    def _build_last_appointment_response(self, context: Dict[str, Any]) -> str:
        """Answer questions about the client's most recent completed or past appointment."""
        client_id = context.get("client_id")
        if not client_id:
            return "I can help with that once I know which client profile to use. Could you share your phone number first?"

        history = get_client_history(client_id)
        now = datetime.now()
        past_appointments = []
        for appointment in history:
            start_time = appointment.get("start_time")
            if not start_time:
                continue
            try:
                start_dt = datetime.strptime(start_time, "%Y-%m-%d %H:%M")
            except ValueError:
                continue
            if start_dt <= now:
                appointment["_start_dt"] = start_dt
                past_appointments.append(appointment)

        if not past_appointments:
            return "I don't see any past appointments on your profile yet."

        last_appointment = max(past_appointments, key=lambda item: item["_start_dt"])
        stylist_name = None
        stylist_id = last_appointment.get("stylist_id")
        if stylist_id:
            stylist = get_stylist_by_id(stylist_id)
            if stylist.get("name"):
                stylist_name = stylist["name"]

        service_name = last_appointment.get("service_name_snapshot") or "your service"
        date_text = last_appointment["_start_dt"].strftime("%Y-%m-%d")
        time_text = last_appointment["_start_dt"].strftime("%H:%M")
        if stylist_name:
            return f"Your last appointment was {service_name} with {stylist_name} on {date_text} at {time_text}."
        return f"I can see your last appointment was {service_name} on {date_text} at {time_text}, but that older booking does not have a stylist saved."

    def process_message(self, user_message: str, user_id: int = 1) -> str:
        """
        Process a user message through the three-layer architecture.

        Args:
            user_message (str): The user's input message
            user_id (int): The user's unique ID (default 1 for demo)

        Returns:
            str: The agent's response
        """
        logger.info(f"User message received: '{user_message}'")

        # --- Conversation Memory: Load context ---
        context = load_context(user_id)
        if context is not None:
            logger.info("Conversation context loaded")
            logger.info(f"Context: {context}")
        else:
            logger.info("No context found, creating new default context")
            context = default_context()

        for key in ["client_id", "client_name", "client_phone"]:
            if self.client_profile.get(key) not in [None, "", []]:
                context[key] = self.client_profile[key]

        try:
            normalized_message_phone = normalize_phone(user_message)
        except ValueError:
            normalized_message_phone = None

        if normalized_message_phone:
            if normalized_message_phone == context.get("client_phone"):
                return "I already have your phone number on file. What would you like to book today?"
            return "Thanks. I already have the phone number step covered. What service would you like to book today?"

        if self._is_last_appointment_question(user_message):
            return self._build_last_appointment_response(context)

        # --- Intent Detection with Conversation Context ---
        combined_message = user_message
        if self.conversation_history:
            last_turn = self.conversation_history[-1]
            last_assistant_response = last_turn.get("response", "")
            combined_message = (
                f"Assistant: {last_assistant_response}\n"
                f"User: {user_message}"
            )
        intent_data = analyze_intent(combined_message)
        logger.info(f"User intent detected: {intent_data.get('intent', 'unknown')}")

        # --- Update context with extracted info (safe merge: do not overwrite with None, empty, or []) ---
        previous_date = context.get("date")
        for key in ["service", "stylist", "date", "time_preference", "time_after", "time_before", "time_direction", "stylist_id", "intent"]:
            new_value = intent_data.get(key)
            if new_value not in [None, "", []]:
                context[key] = new_value

        if self._handle_time_rejection(context, user_message):
            update_context(user_id, context)
            return "No problem. What other day would work better for you?"

        if context.get("date") and context.get("date") != previous_date:
            reset_time_selection(context, reset_date=False)
            context["available_slots_retrieved"] = False
            context["available_slots"] = None
            context["all_available_slots"] = None

        if context.get("stylist") and not context.get("stylist_id"):
            stylist_name = context["stylist"].lower()
            for stylist in context.get("available_stylists", []):
                candidate = stylist.get("name", "").lower()
                if stylist_name in candidate or candidate in stylist_name:
                    context["stylist"] = stylist["name"]
                    context["stylist_id"] = stylist["id"]
                    break

        if intent_data.get("time"):
            resolve_selected_slot(context, intent_data["time"])

        if context.get("available_slots_retrieved") and not context.get("time"):
            if context.get("time_preference"):
                apply_time_preference(context)
            if context.get("time_after") or context.get("time_before"):
                apply_time_bounds(context)
            handle_slot_navigation(context)

        if context.get("time") and context.get("time_direction"):
            context["time_direction"] = None

        if context.get("time") and (context.get("time_after") or context.get("time_before")):
            context["time_after"] = None
            context["time_before"] = None

        if context.get("time") and context.get("time_preference"):
            context["time_preference"] = None

        logger.debug(f"Context after merge: {context}")

        # --- Planner Loop Guard ---
        MAX_AGENT_STEPS = 10
        action_history = []
        execution_result = None
        safe_loop_message = "I'm having trouble completing your booking right now. Let me try again."

        for step in range(MAX_AGENT_STEPS):
            action_plan = create_plan(context, user_message)
            logger.info(f"Action plan: {action_plan}")

            # Handle conversational prompts before tool execution
            if action_plan and action_plan[0] == "ask_service":
                update_context(user_id, context)
                return "What service would you like to book?"
            if action_plan and action_plan[0] == "ask_stylist":
                update_context(user_id, context)
                if self._user_wants_stylist_recommendation(user_message):
                    recommendation_text = self._build_stylist_recommendation(context)
                    if recommendation_text:
                        return recommendation_text
                stylists = context.get("available_stylists", [])
                if not stylists:
                    return "I couldn't find any available stylists for that service right now."

                stylist_names = ", ".join(stylist["name"] for stylist in stylists)
                return f"Which stylist would you like to book with? Available stylists: {stylist_names}."
            if action_plan and action_plan[0] == "ask_date":
                update_context(user_id, context)
                return "What day would you like to book your appointment?"
            if action_plan and action_plan[0] == "ask_time":
                update_context(user_id, context)
                slots_data = context.get("available_slots", {})
                slots = slots_data.get("slots", [])
                requested_time_unavailable = context.get("requested_time_unavailable")
                if not slots:
                    preference = context.get("time_preference")
                    if preference:
                        return f"I couldn't find any {preference} openings on {context.get('date', 'that day')}. Would you like a different time of day or another date?"
                    if context.get("time_after") or context.get("time_before"):
                        parts = []
                        if context.get("time_after"):
                            parts.append(f"after {context['time_after']}")
                        if context.get("time_before"):
                            parts.append(f"before {context['time_before']}")
                        return f"I couldn't find any openings {' and '.join(parts)} on {context.get('date', 'that day')}. Would you like a different time or another date?"
                    return "I found your service details, but I couldn't find any open times yet. Could you share another date or time preference?"

                display_slots = build_display_slots(slots)
                offset = context.get("slot_display_offset", 0)
                visible_slots = display_slots[offset:offset + 5]
                if not visible_slots and offset:
                    context["slot_display_offset"] = 0
                    offset = 0
                    visible_slots = display_slots[:5]

                formatted_slots = []
                for slot in visible_slots:
                    start = slot.get("start")
                    end = slot.get("end")
                    if start and end:
                        formatted_slots.append(f"{start.split()[-1]}-{end.split()[-1]}")

                slot_text = ", ".join(formatted_slots) if formatted_slots else "the available times I found"
                date = context.get("date", "that day")
                guidance = ""
                if len(display_slots) > offset + len(visible_slots):
                    guidance = " You can also say 'later' to see more times."
                elif offset > 0:
                    guidance = " You can also say 'earlier' to go back."
                unavailable_notice = ""
                if requested_time_unavailable:
                    unavailable_notice = f"I don't have {requested_time_unavailable} available on {date}. "
                    context["requested_time_unavailable"] = None
                increment_hint = " We book in 15-minute increments, so you can also ask for a time like 14:15 or 14:30."
                return f"{unavailable_notice}I found openings for {date}: {slot_text}. Which time works best for you?{guidance}{increment_hint}"

            if not action_plan:
                break

            action = action_plan[0]
            action_history.append(action)

            # Detect repeated action loop
            if len(action_history) >= 3 and len(set(action_history[-3:])) == 1:
                logger.warning("Planner loop detected. Breaking execution.")
                return safe_loop_message

            # Tool Execution
            logger.info("Tool execution started")
            execution_result = execute_actions(action_plan, context)
            logger.info("Tool execution finished")

            # Save updated context
            update_context(user_id, context)
            logger.info("Conversation context saved")

            # Only reset context after successful appointment creation
            if (
                execution_result.get("success")
                and "book_appointment" in action_plan
                and execution_result.get("results", {}).get("book_appointment")
            ):
                reset_context(user_id)
                break

            # If execution failed, break
            if execution_result.get("success") is False:
                break

        # --- Generate natural language response using LLM ---
        response = self._generate_response(user_message, intent_data, execution_result, context)

        # Store in conversation history (optional, not persisted)
        self.conversation_history.append({
            "user": user_message,
            "intent": intent_data,
            "context": context.copy(),
            "actions": action_plan if 'action_plan' in locals() else [],
            "results": execution_result,
            "response": response
        })

        return response

    def _generate_response(self, user_message: str, intent_data: Dict[str, Any], execution_result: Dict[str, Any], context_data: Dict[str, Any]) -> str:
        """
        Generate a natural language response using the LLM.

        Args:
            user_message (str): Original user message
            intent_data (Dict): Intent analysis results
            execution_result (Dict): Tool execution results
            context_data (Dict): Current booking context

        Returns:
            str: Natural language response
        """
        if (
            execution_result
            and execution_result.get("success")
            and execution_result.get("results", {}).get("book_appointment")
        ):
            return build_booking_confirmation(context_data, execution_result)

        # Prepare context for LLM
        context = f"""
User message: {user_message}
Detected intent: {intent_data.get('intent', 'unknown')}
Confidence: {intent_data.get('confidence', 0):.2f}

Execution results: {execution_result.get('results', {})}
Errors: {execution_result.get('errors', [])}
"""

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"Based on this context, provide a helpful response to the user:\n\n{context}"}
        ]

        try:
            response = openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=500
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            # Fallback response if LLM fails
            return self._generate_fallback_response(intent_data, execution_result, context_data)

    def _generate_fallback_response(self, intent_data: Dict[str, Any], execution_result: Dict[str, Any], context_data: Dict[str, Any] | None = None) -> str:
        """Generate a fallback response if LLM is unavailable."""
        intent = intent_data.get('intent', 'unknown')
        results = execution_result.get('results', {})

        if intent == 'ask_services' and 'get_services' in results:
            return build_services_response(results)

        elif intent == 'ask_stylists' and 'get_stylists' in results:
            return build_stylists_response(results)

        elif intent == 'book_service':
            if execution_result.get('success'):
                return build_booking_confirmation(context_data or {}, execution_result)
            else:
                return build_booking_error_response(execution_result)

        else:
            return "I'm here to help with your nail salon booking needs. What would you like to know?"


# -------------------------------
# Conversation Loop
# -------------------------------

def run_agent():
    """
    Main conversation loop for the AI agent using the three-layer architecture.
    """
    init_database()

    print("Welcome to the Nail Salon AI Assistant!")
    print("This agent uses a structured three-layer architecture:")
    print("🔍 Intent Layer → 📝 Planner → ⚡ Tool Executor")
    print("Type 'exit' to quit.\n")

    print("Assistant: Welcome! Before we book, may I have your phone number? For example: 555-123-4567.")
    while True:
        raw_phone = input("User: ").strip()
        if raw_phone.lower() in {"exit", "quit"}:
            print("Goodbye!")
            return
        try:
            phone = normalize_phone(raw_phone)
            break
        except ValueError:
            print("Assistant: Please enter a 10-digit phone number. For example: 555-123-4567.")

    existing_client = get_client_by_phone(phone)
    if existing_client:
        client_profile = {
            "client_id": existing_client["id"],
            "client_name": existing_client["name"],
            "client_phone": phone,
        }
        print(f"Assistant: Nice to see you again, {existing_client['name']}. How can I help with your booking today?")
    else:
        print("Assistant: I don't see a profile with that number yet. I'd be happy to get you set up as a new client before we book your appointment.")

        print("Assistant: What name would you like me to use for your profile?")
        client_name = input("User: ").strip()
        while not client_name:
            client_name = input("User: ").strip()

        print("Assistant: What email would you like me to save for appointment confirmations? If you'd prefer to skip it, just type 'skip'.")
        client_email = input("User: ").strip()
        if client_email.lower() == "skip":
            client_email = None

        print("Assistant: Would you like to receive occasional salon updates or promotions by text or email? (yes/no)")
        marketing_answer = input("User: ").strip().lower()
        marketing_opt_in = marketing_answer in {"yes", "y"}

        client_id = upsert_client(
            name=client_name,
            phone=phone,
            email=client_email,
            marketing_opt_in=marketing_opt_in,
        )
        client_profile = {
            "client_id": client_id,
            "client_name": client_name,
            "client_phone": phone,
        }
        print(f"Assistant: Thank you, {client_name}. You're all set, and we can go ahead with your booking now. What would you like to book today?")

    agent = NailSalonAgent(client_profile=client_profile)
    user_id = client_profile["client_id"]

    # Reset context at the start of a new session for this specific client.
    reset_context(user_id)

    while True:
        user_input = input("User: ").strip()
        if user_input.lower() in {"exit", "quit"}:
            print("Goodbye!")
            break

        try:
            response = agent.process_message(user_input, user_id=user_id)
            print(f"Assistant: {response}")
        except Exception as e:
            print(f"Error processing message: {str(e)}")
            print("Assistant: I'm sorry, I encountered an error. Please try again.")


if __name__ == "__main__":
    run_agent()
