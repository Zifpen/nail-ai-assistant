"""
Planner Layer for Nail Salon AI Assistant

This module generates action plans based on detected user intents.
It creates a sequence of actions that the tool executor will perform.

Action sequences are designed to gather necessary information and
complete user requests efficiently.
"""

from typing import List, Dict, Any


class ActionPlanner:
    """Generates action plans based on user intents."""

    def __init__(self):
        self.action_sequences = {
            "ask_services": ["get_services"],
            "ask_stylists": ["get_stylists"],
            "check_availability": [
                "resolve_service",
                "get_stylists",
                "get_stylist_services",
                "get_available_slots",
            ],
            "book_service": [
                "resolve_service",
                "get_stylists",
                "get_stylist_services",
                "get_available_slots",
                "book_appointment",
            ],
        }

    def generate_plan(self, context: Dict[str, Any]) -> List[str]:
        """
        Step-by-step booking planner using conversation context.

        Args:
            context: Conversation context with keys like intent, service, stylist, date, and time.

        Returns:
            List[str]: The next action to execute.
        """
        if not context.get("service_id"):
            if not context.get("service"):
                return ["ask_service"]
            return ["resolve_service"]

        if not context.get("stylist_id"):
            if not context.get("stylists_retrieved"):
                return ["get_stylists"]
            return ["ask_stylist"]

        if not context.get("stylist_services_retrieved"):
            return ["get_stylist_services"]

        if not context.get("date"):
            return ["ask_date"]

        if not context.get("time"):
            if not context.get("available_slots_retrieved"):
                return ["get_available_slots"]
            return ["ask_time"]

        return ["book_appointment"]

    def get_action_requirements(self, action: str) -> Dict[str, Any]:
        """Return input requirements for a planner action."""
        requirements = {
            "resolve_service": {
                "required_params": ["service_name"],
                "optional_params": [],
                "description": "Resolve a service name to canonical form",
            },
            "get_services": {
                "required_params": [],
                "optional_params": [],
                "description": "Retrieve all available services",
            },
            "get_stylists": {
                "required_params": [],
                "optional_params": [],
                "description": "Retrieve all available stylists",
            },
            "get_stylist_services": {
                "required_params": ["stylist_id"],
                "optional_params": [],
                "description": "Get services offered by a specific stylist",
            },
            "get_available_slots": {
                "required_params": ["date", "service_duration"],
                "optional_params": ["stylist_id"],
                "description": "Find available time slots for booking",
            },
            "book_appointment": {
                "required_params": [
                    "client_name",
                    "service_name",
                    "start_time",
                    "end_time",
                    "service_duration",
                    "date",
                ],
                "optional_params": ["stylist_id"],
                "description": "Create a new appointment booking",
            },
            "ask_time": {
                "required_params": [],
                "optional_params": [],
                "description": "Ask the user to choose from the available time slots",
            },
        }

        return requirements.get(
            action,
            {
                "required_params": [],
                "optional_params": [],
                "description": "Unknown action",
            },
        )


def create_plan(context: Dict[str, Any], user_message: str = None) -> List[str]:
    """Convenience function to create an action plan."""
    planner = ActionPlanner()
    return planner.generate_plan(context)


if __name__ == "__main__":
    test_intents = [
        {"intent": "ask_services", "service": None, "date": None, "stylist": None},
        {"intent": "ask_stylists", "service": None, "date": None, "stylist": None},
        {"intent": "book_service", "service": "manicure", "date": "2026-03-15", "stylist": "Anna"},
        {"intent": "check_availability", "service": "pedicure", "date": None, "stylist": None},
    ]

    for intent_data in test_intents:
        plan = create_plan(intent_data)
        print(f"Intent: {intent_data['intent']}")
        print(f"Plan: {plan}")
        print("-" * 50)
