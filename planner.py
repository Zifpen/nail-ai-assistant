"""
Planner Layer for Nail Salon AI Assistant

This module generates action plans based on detected user intents.
It creates a sequence of actions that the tool executor will perform.

Action sequences are designed to gather necessary information and
complete user requests efficiently.
"""

from typing import List, Dict, Any
from service_resolver import resolve_service_name


class ActionPlanner:
    """Generates action plans based on user intents."""

    def __init__(self):
        # Action sequences for each intent
        self.action_sequences = {
            "ask_services": [
                "get_services"
            ],
            "ask_stylists": [
                "get_stylists"
            ],
            "check_availability": [
                "resolve_service",
                "get_stylists",
                "get_stylist_services",
                "get_available_slots"
            ],
            "book_service": [
                "resolve_service",
                "get_stylists",
                "get_stylist_services",
                "get_available_slots",
                "book_appointment"
            ]
        }

    def generate_plan(self, intent_data: Dict[str, Any]) -> List[str]:
        """
        Generate an action plan based on intent analysis.

        Args:
            intent_data (Dict[str, Any]): Intent analysis result from intent_layer

        Returns:
            List[str]: Ordered list of actions to execute
        """
        intent = intent_data.get("intent", "unknown")

        # Get base action sequence
        if intent in self.action_sequences:
            actions = self.action_sequences[intent].copy()
        else:
            # Default fallback for unknown intents
            actions = ["get_services", "get_stylists"]

        # Optimize the plan based on available information
        actions = self._optimize_plan(actions, intent_data)

        return actions

    def _optimize_plan(self, actions: List[str], intent_data: Dict[str, Any]) -> List[str]:
        """
        Optimize the action plan based on available information to avoid unnecessary steps.

        Args:
            actions (List[str]): Base action sequence
            intent_data (Dict[str, Any]): Intent analysis data

        Returns:
            List[str]: Optimized action sequence
        """
        service = intent_data.get("service")
        stylist = intent_data.get("stylist")
        date = intent_data.get("date")

        optimized_actions = []

        for action in actions:
            # Keep resolve_service if we have a service name but need to validate it
            if action == "resolve_service":
                if service:
                    # We have a service name, we should resolve it to get the service_id
                    optimized_actions.append(action)
                # If no service, skip resolution
                continue

            # Skip stylist lookup if stylist is specified and we're not doing booking
            if action == "get_stylists" and stylist and intent_data.get("intent") != "book_service":
                # For non-booking intents, we might not need full stylist list
                # but keep it for now to be safe
                optimized_actions.append(action)
                continue

            # Always include the action if we reach here
            optimized_actions.append(action)

        return optimized_actions

    def get_action_requirements(self, action: str) -> Dict[str, Any]:
        """
        Get the requirements for a specific action.

        Args:
            action (str): The action name

        Returns:
            Dict[str, Any]: Requirements for the action including:
                - required_params: List of required parameters
                - optional_params: List of optional parameters
                - description: Human-readable description
        """
        requirements = {
            "resolve_service": {
                "required_params": ["service_name"],
                "optional_params": [],
                "description": "Resolve a service name to canonical form"
            },
            "get_services": {
                "required_params": [],
                "optional_params": [],
                "description": "Retrieve all available services"
            },
            "get_stylists": {
                "required_params": [],
                "optional_params": [],
                "description": "Retrieve all available stylists"
            },
            "get_stylist_services": {
                "required_params": ["stylist_id"],
                "optional_params": [],
                "description": "Get services offered by a specific stylist"
            },
            "get_available_slots": {
                "required_params": ["date", "service_duration"],
                "optional_params": ["stylist_id"],
                "description": "Find available time slots for booking"
            },
            "book_appointment": {
                "required_params": ["client_name", "service_name", "start_time", "end_time", "service_duration", "date"],
                "optional_params": ["stylist_id"],
                "description": "Create a new appointment booking"
            }
        }

        return requirements.get(action, {
            "required_params": [],
            "optional_params": [],
            "description": "Unknown action"
        })


def create_plan(intent_data: Dict[str, Any]) -> List[str]:
    """
    Convenience function to create an action plan.

    Args:
        intent_data (Dict[str, Any]): Intent analysis result

    Returns:
        List[str]: Ordered list of actions to execute
    """
    planner = ActionPlanner()
    return planner.generate_plan(intent_data)


# Example usage
if __name__ == "__main__":
    # Test the planner
    test_intents = [
        {"intent": "ask_services", "service": None, "date": None, "stylist": None},
        {"intent": "ask_stylists", "service": None, "date": None, "stylist": None},
        {"intent": "book_service", "service": "manicure", "date": "2026-03-15", "stylist": "Anna"},
        {"intent": "check_availability", "service": "pedicure", "date": None, "stylist": None}
    ]

    for intent_data in test_intents:
        plan = create_plan(intent_data)
        print(f"Intent: {intent_data['intent']}")
        print(f"Plan: {plan}")
        print("-" * 50)