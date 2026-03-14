"""Service name resolver for stylist onboarding.

This module provides utilities to normalize stylist-provided service names
and map them to a canonical service entry in the database.

The resolution logic uses fuzzy matching (via rapidfuzz) to map similar
service names to the same canonical service.

Example:
    resolve_service_name("gel manicure") -> {"service_id": 3, "service_name": "Gel Nails"}
"""

from rapidfuzz import process, fuzz

from database import get_all_services, create_service


def resolve_service_name(service_name: str) -> dict:
    """Resolve a stylist-provided service name to a canonical service.

    Args:
        service_name (str): Raw service name provided by a stylist.

    Returns:
        dict: {
            "service_id": int,
            "service_name": str  # the canonical/normalized name stored in DB
        }

    Logic:
        1) Normalize the input (lowercase and strip whitespace)
        2) Load all services from the DB
        3) Use rapidfuzz to find the best fuzzy match
        4) If best match score >= 80 -> use existing service
        5) Otherwise create a new service record and use it
    """

    # Normalize input
    normalized = service_name.strip().lower()

    # Retrieve existing services
    services = get_all_services()

    # Normalize service names for fuzzy matching while keeping access to the original
    normalized_name_to_service = {s["name"].strip().lower(): s for s in services}
    choices = list(normalized_name_to_service.keys())

    best_match = None
    best_score = 0

    if choices:
        best_match, best_score, _ = process.extractOne(
            normalized,
            choices,
            scorer=fuzz.token_sort_ratio,
            score_cutoff=0,
        )

    # If a match is good enough, use it
    if best_match and best_score >= 80:
        service = normalized_name_to_service[best_match]
        return {
            "service_id": service["id"],
            "service_name": service["name"]
        }

    # Otherwise, create a new service entry
    created_id = create_service(normalized)
    return {
        "service_id": created_id,
        "service_name": normalized
    }
