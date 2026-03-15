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
from intent_layer import analyze_intent
from planner import create_plan
from tool_executor import execute_actions
from database import get_services_for_stylist
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

    def __init__(self):
        self.conversation_history = []
        self.system_prompt = SYSTEM_PROMPT

    def _normalize_time_text(self, value: str) -> str:
        """Normalize time text so 9:15 and 09:15 compare the same."""
        value = value.lower().replace(" ", "").replace("to", "-")
        if "-" in value:
            parts = value.split("-", 1)
            return f"{self._normalize_time_text(parts[0])}-{self._normalize_time_text(parts[1])}"

        try:
            parsed = datetime.strptime(value, "%H:%M")
        except ValueError:
            try:
                parsed = datetime.strptime(value, "%I:%M")
            except ValueError:
                return value

        return parsed.strftime("%H:%M")

    def _user_wants_stylist_recommendation(self, user_message: str) -> bool:
        """Detect when the user wants a stylist recommendation."""
        message_lower = user_message.lower()
        recommendation_phrases = [
            "i have no idea",
            "no idea",
            "not sure",
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

    def _slot_matches_preference(self, slot: Dict[str, Any], preference: str) -> bool:
        """Check whether a slot falls into the requested time-of-day bucket."""
        start_full = slot.get("start")
        if not start_full:
            return False

        start_time = datetime.strptime(start_full.split()[-1], "%H:%M").time()
        hour = start_time.hour

        if preference == "morning":
            return hour < 12
        if preference == "afternoon":
            return 12 <= hour < 17
        if preference == "evening":
            return hour >= 17
        return True

    def _slot_matches_bounds(self, slot: Dict[str, Any], time_after: str, time_before: str) -> bool:
        """Check whether a slot respects after/before constraints."""
        start_full = slot.get("start")
        if not start_full:
            return False

        start_value = start_full.split()[-1]
        start_time = datetime.strptime(start_value, "%H:%M")

        if time_after:
            after_time = datetime.strptime(time_after, "%H:%M")
            if start_time < after_time:
                return False

        if time_before:
            before_time = datetime.strptime(time_before, "%H:%M")
            if start_time >= before_time:
                return False

        return True

    def _apply_time_preference(self, context: Dict[str, Any]) -> None:
        """Filter available slots by morning/afternoon/evening preference."""
        preference = context.get("time_preference")
        all_slots_data = context.get("all_available_slots") or context.get("available_slots") or {}
        slots = all_slots_data.get("slots", [])
        if not preference or not slots:
            return

        filtered_slots = [slot for slot in slots if self._slot_matches_preference(slot, preference)]
        context["available_slots"] = {
            **all_slots_data,
            "slots": filtered_slots,
            "total_slots": len(filtered_slots),
        }

    def _apply_time_bounds(self, context: Dict[str, Any]) -> None:
        """Filter available slots by after/before time constraints."""
        time_after = context.get("time_after")
        time_before = context.get("time_before")
        all_slots_data = context.get("all_available_slots") or context.get("available_slots") or {}
        slots = all_slots_data.get("slots", [])
        if not slots or (not time_after and not time_before):
            return

        filtered_slots = [
            slot for slot in slots if self._slot_matches_bounds(slot, time_after, time_before)
        ]
        context["available_slots"] = {
            **all_slots_data,
            "slots": filtered_slots,
            "total_slots": len(filtered_slots),
        }

    def _build_display_slots(self, slots: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
        """Build a friendlier list of representative, non-overlapping slot suggestions."""
        display_slots = []
        last_end = None

        for slot in slots:
            start = slot.get("start")
            end = slot.get("end")
            if not start or not end:
                continue

            start_dt = datetime.strptime(start, "%Y-%m-%d %H:%M")
            end_dt = datetime.strptime(end, "%Y-%m-%d %H:%M")

            if last_end is None or start_dt >= last_end:
                display_slots.append(slot)
                last_end = end_dt

        return display_slots if display_slots else slots

    def _reset_time_selection(self, context: Dict[str, Any], reset_date: bool = False) -> None:
        """Clear the currently selected time and optionally the selected date."""
        context["time"] = None
        context["start_time"] = None
        context["end_time"] = None
        context["selected_slot"] = None
        if reset_date:
            context["date"] = None
        context["available_slots_retrieved"] = False if reset_date else context.get("available_slots_retrieved", False)
        context["available_slots"] = None if reset_date else context.get("available_slots")
        context["all_available_slots"] = None if reset_date else context.get("all_available_slots")
        context["slot_display_offset"] = 0

    def _handle_slot_navigation(self, context: Dict[str, Any]) -> bool:
        """Move the visible slot window forward or backward."""
        direction = context.get("time_direction")
        slots_data = context.get("available_slots") or {}
        slots = self._build_display_slots(slots_data.get("slots", []))
        if not direction or not slots:
            return False

        offset = context.get("slot_display_offset", 0)
        page_size = 5
        if direction == "later":
            if offset + page_size < len(slots):
                context["slot_display_offset"] = offset + page_size
            else:
                context["slot_display_offset"] = offset
        elif direction == "earlier":
            context["slot_display_offset"] = max(0, offset - page_size)
        else:
            return False

        context["time_direction"] = None
        return True

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

        self._reset_time_selection(context, reset_date=True)
        context["time_preference"] = None
        context["time_after"] = None
        context["time_before"] = None
        context["time_direction"] = None
        return True

    def _resolve_selected_slot(self, context: Dict[str, Any], raw_time: str) -> None:
        """Map a user-provided time or time range to one of the fetched available slots."""
        slots_data = context.get("available_slots", {}) or {}
        slots = slots_data.get("slots", [])
        if not raw_time or not slots:
            return

        normalized = self._normalize_time_text(raw_time)
        selected_slot = None

        for slot in slots:
            start_full = slot.get("start")
            end_full = slot.get("end")
            if not start_full or not end_full:
                continue

            start_time = self._normalize_time_text(start_full.split()[-1])
            end_time = self._normalize_time_text(end_full.split()[-1])
            range_text = f"{start_time}-{end_time}"

            if normalized == range_text or normalized == start_time:
                selected_slot = slot
                break

        if selected_slot:
            context["time"] = selected_slot["start"].split()[-1]
            context["start_time"] = selected_slot["start"]
            context["end_time"] = selected_slot["end"]
            context["selected_slot"] = selected_slot
            context["available_slots_retrieved"] = True

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
        for key in ["service", "stylist", "date", "time", "time_preference", "time_after", "time_before", "time_direction", "stylist_id", "intent"]:
            new_value = intent_data.get(key)
            if new_value not in [None, "", []]:
                context[key] = new_value

        if self._handle_time_rejection(context, user_message):
            update_context(user_id, context)
            return "No problem. What other day would work better for you?"

        if context.get("date") and context.get("date") != previous_date:
            self._reset_time_selection(context, reset_date=False)
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
            self._resolve_selected_slot(context, intent_data["time"])

        if context.get("available_slots_retrieved") and not context.get("time"):
            if context.get("time_preference"):
                self._apply_time_preference(context)
            if context.get("time_after") or context.get("time_before"):
                self._apply_time_bounds(context)
            self._handle_slot_navigation(context)

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
                    return "Which stylist would you like to book with?"

                stylist_names = ", ".join(stylist["name"] for stylist in stylists)
                return f"Which stylist would you like to book with? Available stylists: {stylist_names}."
            if action_plan and action_plan[0] == "ask_date":
                update_context(user_id, context)
                return "What day would you like to book your appointment?"
            if action_plan and action_plan[0] == "ask_time":
                update_context(user_id, context)
                slots_data = context.get("available_slots", {})
                slots = slots_data.get("slots", [])
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

                display_slots = self._build_display_slots(slots)
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
                increment_hint = " We book in 15-minute increments, so you can also ask for a time like 14:15 or 14:30."
                return f"I found openings for {date}: {slot_text}. Which time works best for you?{guidance}{increment_hint}"

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

    def _generate_booking_confirmation(self, context: Dict[str, Any], execution_result: Dict[str, Any]) -> str:
        """Build a stable confirmation message for successful bookings."""
        service_name = context.get("service_name") or context.get("service") or "your service"
        stylist_name = context.get("stylist") or "your stylist"
        date = context.get("date")
        start_time = context.get("start_time")

        if start_time and " " in start_time:
            _, start_clock = start_time.split(" ", 1)
        else:
            start_clock = context.get("time")

        booking_result = execution_result.get("results", {}).get("book_appointment", {})
        appointment_id = booking_result.get("appointment_id")

        details = []
        if service_name:
            details.append(service_name)
        if date:
            details.append(f"on {date}")
        if start_clock:
            details.append(f"at {start_clock}")
        if stylist_name:
            details.append(f"with {stylist_name}")

        detail_text = " ".join(details).strip()
        confirmation = f"Your appointment is confirmed for {detail_text}.".replace("for on", "for")
        if appointment_id:
            confirmation += f" Your confirmation number is {appointment_id}."
        return confirmation

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
            return self._generate_booking_confirmation(context_data, execution_result)

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
            services = results['get_services']
            # Deduplicate by service name while preserving order
            seen = set()
            unique_services = []
            for s in services:
                name = s['name']
                if name not in seen:
                    seen.add(name)
                    unique_services.append(name)
            return f"We offer the following services: {', '.join(unique_services)}."

        elif intent == 'ask_stylists' and 'get_stylists' in results:
            stylists = results['get_stylists']
            stylist_names = [s['name'] for s in stylists]
            return f"Our stylists are: {', '.join(stylist_names)}."

        elif intent == 'book_service':
            if execution_result.get('success'):
                return self._generate_booking_confirmation(context_data or {}, execution_result)
            else:
                errors = execution_result.get('errors', [])
                return f"I encountered some issues booking your appointment: {', '.join(errors)}. Please try again."

        else:
            return "I'm here to help with your nail salon booking needs. What would you like to know?"


# -------------------------------
# Conversation Loop
# -------------------------------

def run_agent():
    """
    Main conversation loop for the AI agent using the three-layer architecture.
    """
    print("Welcome to the Nail Salon AI Assistant!")
    print("This agent uses a structured three-layer architecture:")
    print("🔍 Intent Layer → 📝 Planner → ⚡ Tool Executor")
    print("Type 'exit' to quit.\n")

    agent = NailSalonAgent()
    user_id = 1  # For demo/testing, use a fixed user_id. Replace with real user ID in production.

    # Reset context at the start of a new session so tests don't inherit stale booking state.
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
