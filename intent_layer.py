"""
Intent Layer for Nail Salon AI Assistant

This module analyzes user messages and detects user intents for the booking system.
It extracts structured information from natural language input.

Supported intents:
- ask_services: User wants to know what services are offered
- ask_stylists: User wants to know about available stylists
- check_availability: User wants to check available time slots
- book_service: User wants to book an appointment

Returns structured intent objects with extracted parameters.
"""

import re
from datetime import datetime, timedelta
from typing import Dict, Any, Optional


class IntentDetector:
    """Detects user intents from natural language messages."""

    def __init__(self):
        # Current date for relative date parsing
        self.today = datetime.now().date()

        # Intent patterns with associated keywords
        self.intent_patterns = {
            "ask_services": [
                r"what services", r"services offered", r"what do you offer",
                r"service menu", r"what can i get", r"available services"
            ],
            "ask_stylists": [
                r"who are your stylists", r"stylists available", r"who works here",
                r"available stylists", r"who can do", r"stylist list"
            ],
            "check_availability": [
                r"available times", r"when are you open", r"free slots",
                r"available appointments", r"open times", r"booking times"
            ],
            "book_service": [
                r"book.*appointment", r"make.*appointment", r"schedule.*appointment",
                r"i want to book", r"can i book", r"schedule for", r"appointment for",
                r"can i schedule", r"i would like to", r"i need to", r"book a",
                r"schedule a", r"make a", r"get a"
            ]
        }

        # Service name patterns for extraction
        self.service_patterns = [
            r"manicure", r"pedicure", r"acrylic", r"gel.*extensions?",
            r"hard.*gel", r"gel.*nails?", r"nail.*art", r"polish"
        ]

        # Date patterns for extraction
        self.date_patterns = {
            "today": self.today,
            "tomorrow": self.today + timedelta(days=1),
            "next week": self.today + timedelta(days=7),
            "next monday": self._get_next_weekday(0),  # Monday = 0
            "next tuesday": self._get_next_weekday(1),
            "next wednesday": self._get_next_weekday(2),
            "next thursday": self._get_next_weekday(3),
            "next friday": self._get_next_weekday(4),
            "next saturday": self._get_next_weekday(5),
            "next sunday": self._get_next_weekday(6)
        }

    def _get_next_weekday(self, weekday: int) -> datetime.date:
        """Get the next occurrence of a specific weekday (0=Monday, 6=Sunday)."""
        days_ahead = weekday - self.today.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        return self.today + timedelta(days=days_ahead)

    def _extract_service(self, message: str) -> Optional[str]:
        """Extract service name from message using fuzzy matching."""
        message_lower = message.lower()

        for pattern in self.service_patterns:
            match = re.search(pattern, message_lower)
            if match:
                return match.group()

        return None

    def _extract_date(self, message: str) -> Optional[str]:
        """Extract date from message."""
        message_lower = message.lower()

        # Check for relative dates
        for date_name, date_obj in self.date_patterns.items():
            if date_name in message_lower:
                return date_obj.strftime("%Y-%m-%d")

        # Check for explicit dates (YYYY-MM-DD format)
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", message)
        if date_match:
            return date_match.group(1)

        # Check for MM/DD format
        date_match = re.search(r"(\d{1,2}/\d{1,2})", message)
        if date_match:
            try:
                month, day = map(int, date_match.group(1).split("/"))
                year = self.today.year
                date_obj = datetime(year, month, day).date()
                # If the date is in the past, assume next year
                if date_obj < self.today:
                    date_obj = datetime(year + 1, month, day).date()
                return date_obj.strftime("%Y-%m-%d")
            except ValueError:
                pass

        return None

    def _extract_stylist(self, message: str) -> Optional[str]:
        """Extract stylist name from message."""
        # Look for common stylist name patterns
        stylist_match = re.search(r"with\s+(\w+)", message.lower())
        if stylist_match:
            return stylist_match.group(1).title()

        return None

    def detect_intent(self, message: str) -> Dict[str, Any]:
        """
        Analyze a user message and return structured intent information.

        Args:
            message (str): The user's message

        Returns:
            Dict[str, Any]: Structured intent object with keys:
                - intent: str (ask_services, ask_stylists, check_availability, book_service)
                - service: str or None (extracted service name)
                - date: str or None (extracted date in YYYY-MM-DD format)
                - stylist: str or None (extracted stylist name)
                - confidence: float (0.0-1.0, confidence score)
        """
        message_lower = message.lower()

        # Default result
        result = {
            "intent": "unknown",
            "service": None,
            "date": None,
            "stylist": None,
            "confidence": 0.0
        }

        # Check each intent pattern
        best_match = None
        best_score = 0.0

        for intent, patterns in self.intent_patterns.items():
            for pattern in patterns:
                if re.search(pattern, message_lower):
                    # Calculate confidence based on pattern match
                    confidence = 0.8  # Base confidence for pattern match

                    # Boost confidence for exact matches or multiple keywords
                    if intent == "book_service" and ("book" in message_lower or "appointment" in message_lower):
                        confidence = 0.95
                    elif intent == "ask_services" and "services" in message_lower:
                        confidence = 0.9
                    elif intent == "ask_stylists" and "stylist" in message_lower:
                        confidence = 0.9

                    if confidence > best_score:
                        best_score = confidence
                        best_match = intent

        if best_match:
            result["intent"] = best_match
            result["confidence"] = best_score

            # Extract additional information based on intent
            result["service"] = self._extract_service(message)
            result["date"] = self._extract_date(message)
            result["stylist"] = self._extract_stylist(message)

        return result


def analyze_intent(message: str) -> Dict[str, Any]:
    """
    Convenience function to analyze user intent.

    Args:
        message (str): User message

    Returns:
        Dict[str, Any]: Structured intent information
    """
    detector = IntentDetector()
    return detector.detect_intent(message)


# Example usage
if __name__ == "__main__":
    # Test the intent detector
    test_messages = [
        "What services do you offer?",
        "Who are your stylists?",
        "I want to book a manicure tomorrow",
        "Are there any available times next week?",
        "Can I schedule a pedicure with Anna?"
    ]

    for msg in test_messages:
        intent = analyze_intent(msg)
        print(f"Message: {msg}")
        print(f"Intent: {intent}")
        print("-" * 50)