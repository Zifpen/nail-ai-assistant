from datetime import datetime
from typing import Any, Dict, List


def normalize_time_text(value: str) -> str:
    """Normalize time text so 9:15 and 09:15 compare the same."""
    value = value.lower().replace(" ", "").replace("to", "-")
    if "-" in value:
        parts = value.split("-", 1)
        return f"{normalize_time_text(parts[0])}-{normalize_time_text(parts[1])}"

    try:
        parsed = datetime.strptime(value, "%H:%M")
    except ValueError:
        try:
            parsed = datetime.strptime(value, "%I:%M")
        except ValueError:
            return value

    return parsed.strftime("%H:%M")


def slot_matches_preference(slot: Dict[str, Any], preference: str) -> bool:
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


def slot_matches_bounds(slot: Dict[str, Any], time_after: str, time_before: str) -> bool:
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


def apply_time_preference(context: Dict[str, Any]) -> None:
    """Filter available slots by morning/afternoon/evening preference."""
    preference = context.get("time_preference")
    all_slots_data = context.get("all_available_slots") or context.get("available_slots") or {}
    slots = all_slots_data.get("slots", [])
    if not preference or not slots:
        return

    filtered_slots = [slot for slot in slots if slot_matches_preference(slot, preference)]
    context["available_slots"] = {
        **all_slots_data,
        "slots": filtered_slots,
        "total_slots": len(filtered_slots),
    }


def apply_time_bounds(context: Dict[str, Any]) -> None:
    """Filter available slots by after/before time constraints."""
    time_after = context.get("time_after")
    time_before = context.get("time_before")
    all_slots_data = context.get("all_available_slots") or context.get("available_slots") or {}
    slots = all_slots_data.get("slots", [])
    if not slots or (not time_after and not time_before):
        return

    filtered_slots = [
        slot for slot in slots if slot_matches_bounds(slot, time_after, time_before)
    ]
    context["available_slots"] = {
        **all_slots_data,
        "slots": filtered_slots,
        "total_slots": len(filtered_slots),
    }


def build_display_slots(slots: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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


def reset_time_selection(context: Dict[str, Any], reset_date: bool = False) -> None:
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


def handle_slot_navigation(context: Dict[str, Any]) -> bool:
    """Move the visible slot window forward or backward."""
    direction = context.get("time_direction")
    slots_data = context.get("available_slots") or {}
    slots = build_display_slots(slots_data.get("slots", []))
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


def resolve_selected_slot(context: Dict[str, Any], raw_time: str) -> bool:
    """Map a user-provided time or time range to one of the fetched available slots."""
    slots_data = context.get("available_slots", {}) or {}
    slots = slots_data.get("slots", [])
    if not raw_time or not slots:
        return False

    normalized = normalize_time_text(raw_time)
    selected_slot = None

    for slot in slots:
        start_full = slot.get("start")
        end_full = slot.get("end")
        if not start_full or not end_full:
            continue

        start_time = normalize_time_text(start_full.split()[-1])
        end_time = normalize_time_text(end_full.split()[-1])
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
        context["requested_time_unavailable"] = None
        return True

    context["requested_time_unavailable"] = normalized
    return False
