"""
Scheduling Module for Nail Salon AI Booking Assistant

Generates all valid appointment time slots while minimizing unusable gap time.
Returns ALL valid slots that satisfy scheduling rules (no ranking or prioritization).

Main function: get_available_slots()
"""

from datetime import datetime, timedelta
from typing import List, Dict, Tuple
import math


def find_free_gaps(
    appointments: List[Dict[str, str]],
    working_hours: Dict[str, str],
    date: str
) -> List[Tuple[datetime, datetime]]:
    """
    Find all free time gaps between existing appointments within working hours.
    
    Args:
        appointments: List of existing appointments with "start" and "end" times
        working_hours: {"start": "HH:MM", "end": "HH:MM"} format
        date: Date for appointments (YYYY-MM-DD format)
    
    Returns:
        List of (gap_start, gap_end) datetime tuples
    
    Example:
        >>> gaps = find_free_gaps(
        ...     appointments=[{"start": "2026-03-12 10:00", "end": "2026-03-12 11:00"}],
        ...     working_hours={"start": "09:00", "end": "18:00"},
        ...     date="2026-03-12"
        ... )
        >>> gaps
        [(datetime(..., 09:00), datetime(..., 10:00)), (datetime(..., 11:00), datetime(..., 18:00))]
    """
    # Parse working hours
    work_start = datetime.strptime(
        f"{date} {working_hours['start']}", "%Y-%m-%d %H:%M"
    )
    work_end = datetime.strptime(
        f"{date} {working_hours['end']}", "%Y-%m-%d %H:%M"
    )

    # Parse and sort appointments
    parsed_appointments = []
    for appt in appointments:
        start = datetime.strptime(appt["start"], "%Y-%m-%d %H:%M")
        end = datetime.strptime(appt["end"], "%Y-%m-%d %H:%M")
        parsed_appointments.append((start, end))

    parsed_appointments.sort(key=lambda x: x[0])

    gaps = []

    # If no appointments, entire day is free
    if not parsed_appointments:
        gaps.append((work_start, work_end))
        return gaps

    # Gap before first appointment
    first_appt_start = parsed_appointments[0][0]
    if work_start < first_appt_start:
        gaps.append((work_start, first_appt_start))

    # Gaps between appointments
    for i in range(len(parsed_appointments) - 1):
        gap_start = parsed_appointments[i][1]
        gap_end = parsed_appointments[i + 1][0]

        if gap_start < gap_end:
            gaps.append((gap_start, gap_end))

    # Gap after last appointment
    last_appt_end = parsed_appointments[-1][1]
    if last_appt_end < work_end:
        gaps.append((last_appt_end, work_end))

    return gaps


def calculate_gap_capacity(
    gap_start: datetime,
    gap_end: datetime,
    min_service_duration: int
) -> int:
    """
    Determine how many minimum-length services can fit in the gap.
    
    Args:
        gap_start: Start of gap (datetime)
        gap_end: End of gap (datetime)
        min_service_duration: Shortest service duration in minutes
    
    Returns:
        Maximum number of services that fit: floor(gap_minutes / min_service_duration)
    
    Example:
        >>> gap_start = datetime(2026, 3, 12, 11, 0)
        >>> gap_end = datetime(2026, 3, 12, 14, 0)
        >>> calculate_gap_capacity(gap_start, gap_end, 45)
        4  # 180 minutes / 45 = 4 services
    """
    gap_minutes = int((gap_end - gap_start).total_seconds() / 60)
    capacity = math.floor(gap_minutes / min_service_duration)
    return capacity


def generate_candidate_slots(
    gap_start: datetime,
    gap_end: datetime,
    service_duration: int,
    slot_interval: int
) -> List[Tuple[datetime, datetime]]:
    """
    Generate all valid start times aligned to the slot grid.
    
    All slots must satisfy: start_time + service_duration <= gap_end
    All start times must align to slot_interval.
    
    Args:
        gap_start: Start of the free gap
        gap_end: End of the free gap
        service_duration: Duration of requested service in minutes
        slot_interval: Time grid granularity in minutes (15, 30, 60)
    
    Returns:
        List of (slot_start, slot_end) datetime tuples
    
    Example:
        >>> gap_start = datetime(2026, 3, 12, 11, 0)
        >>> gap_end = datetime(2026, 3, 12, 14, 0)
        >>> slots = generate_candidate_slots(gap_start, gap_end, 60, 15)
        >>> slots
        [
            (datetime(..., 11:00), datetime(..., 12:00)),
            (datetime(..., 11:15), datetime(..., 12:15)),
            (datetime(..., 11:30), datetime(..., 12:30)),
            ...
        ]
    """
    candidates = []

    # Find first aligned slot in this gap
    minutes_offset = gap_start.minute % slot_interval
    if minutes_offset != 0:
        # Align to next slot grid point
        align_minutes = slot_interval - minutes_offset
        current = gap_start + timedelta(minutes=align_minutes)
    else:
        current = gap_start

    # Generate all aligned slots that fit within the gap
    while current + timedelta(minutes=service_duration) <= gap_end:
        slot_end = current + timedelta(minutes=service_duration)
        candidates.append((current, slot_end))
        current += timedelta(minutes=slot_interval)

    return candidates


def filter_bad_slots(
    slots: List[Tuple[datetime, datetime]],
    gap_end: datetime,
    service_duration: int,
    min_service_duration: int,
    gap_capacity: int
) -> List[Tuple[datetime, datetime]]:
    """
    Remove slots that create unusable leftover fragments.
    
    Rule: If remaining gap < min_service_duration, avoid that slot.
    Exception: If gap_capacity == 1, return ALL slots (no filtering).
    
    Args:
        slots: List of candidate slots (start, end) as datetime tuples
        gap_end: End of the gap
        service_duration: Duration of service in minutes
        min_service_duration: Shortest possible service in minutes
        gap_capacity: Number of min-duration services that fit in gap
    
    Returns:
        Filtered list of acceptable slots
    
    Example:
        >>> # gap: 11:00-14:00 (180 min), min_service: 45 min, capacity: 4
        >>> # 11:00-12:00 leaves 120 min (usable) -> KEEP
        >>> # 13:15-14:15 leaves 0 min (perfect) -> KEEP
        >>> # 13:16-14:16 leaves -1 min (out of gap) -> filtered by generate_candidate_slots
        >>> filtered = filter_bad_slots(slots, gap_end, 60, 45, 4)
    """
    # Single-service gaps: return ALL slots (Rule 3)
    if gap_capacity == 1:
        return slots

    # Multi-service gaps: filter out slots creating small fragments
    filtered = []
    for slot_start, slot_end in slots:
        leftover_minutes = int((gap_end - slot_end).total_seconds() / 60)

        # Accept if no leftover or leftover is usable
        if leftover_minutes == 0 or leftover_minutes >= min_service_duration:
            filtered.append((slot_start, slot_end))

    # If all slots were filtered, return all candidates
    # (better to show options than return nothing)
    return filtered if filtered else slots


def get_available_slots(
    appointments: List[Dict[str, str]],
    service_duration: int,
    working_hours: Dict[str, str],
    min_service_duration: int,
    date: str,
    slot_interval: int = 15
) -> List[Dict[str, str]]:
    """
    Generate ALL valid appointment time slots.
    
    Returns all slots that satisfy scheduling rules without ranking or prioritization.
    Uses the following functions:
    1. find_free_gaps() - identifies free time intervals
    2. calculate_gap_capacity() - determines how many services fit
    3. generate_candidate_slots() - creates aligned time slots
    4. filter_bad_slots() - removes slots creating unusable fragments
    
    Args:
        appointments: List of existing bookings with "start" and "end" times
            Example: [
                {"start": "2026-03-12 10:00", "end": "2026-03-12 11:00"},
                {"start": "2026-03-12 13:00", "end": "2026-03-12 14:00"}
            ]
        
        service_duration: Length of requested service in minutes
            Example: 60
        
        working_hours: Salon operating hours
            Example: {"start": "09:00", "end": "18:00"}
        
        min_service_duration: Shortest possible service in minutes
            Example: 45
        
        date: Date for the appointment (YYYY-MM-DD format)
            Example: "2026-03-12"
        
        slot_interval: Time grid granularity in minutes (default: 15)
            Options: 15 (XX:00/15/30/45), 30 (XX:00/30), 60 (hourly)
    
    Returns:
        List of all valid appointment slots, each with "start" and "end" times:
        [
            {"start": "2026-03-12 11:00", "end": "2026-03-12 12:00"},
            {"start": "2026-03-12 11:15", "end": "2026-03-12 12:15"},
            {"start": "2026-03-12 14:00", "end": "2026-03-12 15:00"}
        ]
    
    Scheduling Rules Applied:
        Rule 1: Find all free gaps between appointments
        Rule 2: Calculate gap capacity (floor division)
        Rule 3: Single-service gaps return ALL slots (no filtering)
        Rule 4: Multi-service gaps filter unusable fragments
        Rule 5: All slots align to slot_interval grid
    
    Example:
        >>> slots = get_available_slots(
        ...     appointments=[
        ...         {"start": "2026-03-12 10:00", "end": "2026-03-12 11:00"},
        ...         {"start": "2026-03-12 14:00", "end": "2026-03-12 15:00"}
        ...     ],
        ...     service_duration=60,
        ...     working_hours={"start": "09:00", "end": "18:00"},
        ...     min_service_duration=45,
        ...     date="2026-03-12"
        ... )
        >>> len(slots)
        7
        >>> slots[0]
        {'start': '2026-03-12 09:00', 'end': '2026-03-12 10:00'}
    """
    # Step 1: Find all free gaps
    gaps = find_free_gaps(appointments, working_hours, date)

    if not gaps:
        return []

    all_slots = []

    # Step 2-4: For each gap, generate, filter, and collect slots
    for gap_start, gap_end in gaps:
        # Step 2: Calculate gap capacity
        gap_capacity = calculate_gap_capacity(gap_start, gap_end, min_service_duration)

        if gap_capacity == 0:
            # Gap is too small for any service
            continue

        # Step 3: Generate all candidate slots
        candidates = generate_candidate_slots(
            gap_start, gap_end, service_duration, slot_interval
        )

        if not candidates:
            # No slots fit in this gap
            continue

        # Step 4: Filter bad slots (or keep all for single-service gaps)
        valid_slots = filter_bad_slots(
            candidates,
            gap_end,
            service_duration,
            min_service_duration,
            gap_capacity
        )

        # Add to result set
        all_slots.extend(valid_slots)

    # Convert datetime tuples to string dictionaries
    result = [
        {
            "start": slot_start.strftime("%Y-%m-%d %H:%M"),
            "end": slot_end.strftime("%Y-%m-%d %H:%M")
        }
        for slot_start, slot_end in all_slots
    ]

    return result


# ============================================================================
# MAIN - EXAMPLE USAGE
# ============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("SCHEDULER MODULE - EXAMPLE USAGE")
    print("=" * 70)

    # Example 1: Simple schedule with gaps
    print("\nEXAMPLE 1: Simple schedule with multiple gaps")
    print("-" * 70)

    slots = get_available_slots(
        appointments=[
            {"start": "2026-03-12 10:00", "end": "2026-03-12 11:00"},
            {"start": "2026-03-12 13:00", "end": "2026-03-12 14:00"}
        ],
        service_duration=60,
        working_hours={"start": "09:00", "end": "18:00"},
        min_service_duration=45,
        date="2026-03-12"
    )

    print(f"\nFound {len(slots)} available slots:\n")
    for i, slot in enumerate(slots, 1):
        print(f"{i}. {slot['start']} → {slot['end']}")

    # Example 2: Empty schedule
    print("\n" + "=" * 70)
    print("EXAMPLE 2: Empty schedule (entire day free)")
    print("-" * 70)

    slots = get_available_slots(
        appointments=[],
        service_duration=60,
        working_hours={"start": "09:00", "end": "18:00"},
        min_service_duration=45,
        date="2026-03-12"
    )

    print(f"\nFound {len(slots)} available slots (showing first 5):\n")
    for i, slot in enumerate(slots[:5], 1):
        print(f"{i}. {slot['start']} → {slot['end']}")
    if len(slots) > 5:
        print(f"... and {len(slots) - 5} more")

    # Example 3: Fully booked
    print("\n" + "=" * 70)
    print("EXAMPLE 3: Fully booked day")
    print("-" * 70)

    slots = get_available_slots(
        appointments=[
            {"start": "2026-03-12 09:00", "end": "2026-03-12 18:00"}
        ],
        service_duration=60,
        working_hours={"start": "09:00", "end": "18:00"},
        min_service_duration=45,
        date="2026-03-12"
    )

    print(f"\nFound {len(slots)} available slots")
    if not slots:
        print("(No availability - day is fully booked)")

    # Example 4: Single-service gap (Rule 3)
    print("\n" + "=" * 70)
    print("EXAMPLE 4: Single-service gap (Rule 3 - no filtering)")
    print("-" * 70)
    print("""
Appointments:
  • 10:00-11:00
  • 12:00-18:00

Free gap:
  • 11:00-12:00 (60 minutes) = capacity 1

Min service: 45 minutes
Requesting: 45-minute service

Expected: ALL slots returned (no filtering for single-service gaps)
  • 11:00-11:45 (leaves 15min unusable - but INCLUDED!)
  • 11:15-12:00 (leaves 15min unusable - but INCLUDED!)
""")

    slots = get_available_slots(
        appointments=[
            {"start": "2026-03-12 10:00", "end": "2026-03-12 11:00"},
            {"start": "2026-03-12 12:00", "end": "2026-03-12 18:00"}
        ],
        service_duration=45,
        working_hours={"start": "09:00", "end": "18:00"},
        min_service_duration=45,
        date="2026-03-12",
        slot_interval=15
    )

    print(f"Found {len(slots)} slots:\n")
    for i, slot in enumerate(slots, 1):
        print(f"{i}. {slot['start']} → {slot['end']}")
