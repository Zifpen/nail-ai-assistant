


from database import get_db_connection
import json
from typing import Dict, Any
from datetime import datetime
from logger import get_logger

def init_conversations_table():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            context_json TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )
    conn.commit()
    conn.close()


init_conversations_table()

def print_all_conversations():
    """Diagnostic: Print all rows in the conversations table."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT user_id, context_json, updated_at FROM conversations")
        rows = cursor.fetchall()
        logger.info(f"All conversations rows: {rows}")
    finally:
        conn.close()

logger = get_logger("memory")

def load_context(user_id: int) -> Dict[str, Any] | None:
    """Load the conversation context for a user. Returns dict if found, None if not found."""
    logger.debug(f"load_context: user_id={user_id} (type: {type(user_id)})")
    print_all_conversations()  # Diagnostic: print all rows before loading
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT context_json FROM conversations WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row:
            logger.info(f"Loaded context for user_id={user_id}")
            return json.loads(row["context_json"])
        else:
            logger.info(f"No context found in DB for user_id: {user_id}")
            return None
    finally:
        conn.close()

def update_context(user_id: int, context: Dict[str, Any]) -> None:
    """Update or insert the conversation context for a user."""
    context_json = json.dumps(context)
    logger.debug(f"update_context: user_id={user_id} (type: {type(user_id)})")
    logger.debug(f"Saving context for user_id={user_id}")
    if user_id is None:
        logger.error("Attempted to write context with user_id=None!")
        return
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            '''
            INSERT INTO conversations (user_id, context_json)
            VALUES (?, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET
                context_json = excluded.context_json,
                updated_at = CURRENT_TIMESTAMP
            ''',
            (user_id, context_json)
        )
        conn.commit()
        cursor.execute("SELECT COUNT(*) FROM conversations")
        row_count = cursor.fetchone()[0]
        logger.info(f"Saved context for user_id={user_id}. Total rows in conversations: {row_count}")
        print_all_conversations()  # Diagnostic: print all rows after saving
    finally:
        conn.close()

def reset_context(user_id: int) -> None:
    """Delete the conversation context for a user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()

# Default context structure for reference
def default_context() -> Dict[str, Any]:
    return {
        "intent": None,
        "service": None,
        "client_id": None,
        "client_name": None,
        "client_phone": None,
        "stylist": None,
        "stylist_id": None,
        "stylists_retrieved": False,
        "available_stylists": [],
        "no_stylist_preference": False,
        "no_stylists_available": False,
        "stylist_services_retrieved": False,
        "date": None,
        "time": None,
        "time_preference": None,
        "time_after": None,
        "time_before": None,
        "time_direction": None,
        "available_slots_retrieved": False,
        "available_slots": None,
        "all_available_slots": None,
        "slot_display_offset": 0,
        "start_time": None,
        "end_time": None,
        "selected_slot": None,
        "requested_time_unavailable": None,
    }
