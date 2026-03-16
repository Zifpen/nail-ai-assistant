from typing import Any, Dict


def build_booking_confirmation(context: Dict[str, Any], execution_result: Dict[str, Any]) -> str:
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


def build_services_response(results: Dict[str, Any]) -> str:
    """Build a response listing available services."""
    services = results["get_services"]
    seen = set()
    unique_services = []
    for service in services:
        name = service["name"]
        if name not in seen:
            seen.add(name)
            unique_services.append(name)
    return f"We offer the following services: {', '.join(unique_services)}."


def build_stylists_response(results: Dict[str, Any]) -> str:
    """Build a response listing available stylists."""
    stylists = results["get_stylists"]
    stylist_names = [stylist["name"] for stylist in stylists]
    return f"Our stylists are: {', '.join(stylist_names)}."


def build_booking_error_response(execution_result: Dict[str, Any]) -> str:
    """Build a booking failure response."""
    errors = execution_result.get("errors", [])
    return f"I encountered some issues booking your appointment: {', '.join(errors)}. Please try again."
