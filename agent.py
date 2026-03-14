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

    def process_message(self, user_message: str) -> str:
        """
        Process a user message through the three-layer architecture.

        Args:
            user_message (str): The user's input message

        Returns:
            str: The agent's response
        """
        print(f"\n🔍 Analyzing intent for: '{user_message}'")

        # Layer 1: Intent Detection
        intent_data = analyze_intent(user_message)
        print(f"📋 Detected intent: {intent_data}")

        # Layer 2: Action Planning
        action_plan = create_plan(intent_data)
        print(f"📝 Generated action plan: {action_plan}")

        # Layer 3: Tool Execution
        execution_result = execute_actions(action_plan, intent_data)

        # Generate natural language response using LLM
        response = self._generate_response(user_message, intent_data, execution_result)

        # Store in conversation history
        self.conversation_history.append({
            "user": user_message,
            "intent": intent_data,
            "actions": action_plan,
            "results": execution_result,
            "response": response
        })

        return response

    def _generate_response(self, user_message: str, intent_data: Dict[str, Any], execution_result: Dict[str, Any]) -> str:
        """
        Generate a natural language response using the LLM.

        Args:
            user_message (str): Original user message
            intent_data (Dict): Intent analysis results
            execution_result (Dict): Tool execution results

        Returns:
            str: Natural language response
        """
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
            return self._generate_fallback_response(intent_data, execution_result)

    def _generate_fallback_response(self, intent_data: Dict[str, Any], execution_result: Dict[str, Any]) -> str:
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
                return "I've successfully booked your appointment! You'll receive a confirmation shortly."
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

    while True:
        user_input = input("User: ").strip()
        if user_input.lower() in {"exit", "quit"}:
            print("Goodbye!")
            break

        try:
            response = agent.process_message(user_input)
            print(f"Assistant: {response}")
        except Exception as e:
            print(f"Error processing message: {str(e)}")
            print("Assistant: I'm sorry, I encountered an error. Please try again.")


if __name__ == "__main__":
    run_agent()