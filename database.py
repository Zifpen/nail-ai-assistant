"""
Database layer for nail salon appointment system.

Retrieves appointment data from SQLite and provides it in the format
expected by the scheduler module.
"""

import sqlite3
import re
from typing import List, Dict
from datetime import datetime

# Import scheduler for slot validation
from scheduler import get_available_slots



# Database configuration

import os
from logger import get_logger
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "salon.db")
logger = get_logger("database")


def normalize_phone(phone: str) -> str:
    """Normalize a phone number into a stable 10-digit US format."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        raise ValueError("Phone number must contain 10 digits")
    return digits


def _column_exists(cursor: sqlite3.Cursor, table_name: str, column_name: str) -> bool:
    """Check whether a column exists on a table."""
    cursor.execute(f"PRAGMA table_info({table_name})")
    return any(row[1] == column_name for row in cursor.fetchall())


def _migrate_appointments_schema(cursor: sqlite3.Cursor) -> None:
    """Add newer appointment columns without destroying existing data."""
    columns_to_add = [
        ("client_id", "INTEGER"),
        ("client_user_id", "INTEGER"),
        ("stylist_id", "INTEGER"),
        ("service_id", "INTEGER"),
        ("client_name_snapshot", "TEXT"),
        ("service_name_snapshot", "TEXT"),
        ("status", "TEXT NOT NULL DEFAULT 'booked'"),
        ("notes", "TEXT"),
        ("created_at", "TEXT"),
        ("updated_at", "TEXT"),
    ]

    for column_name, column_type in columns_to_add:
        if not _column_exists(cursor, "appointments", column_name):
            cursor.execute(f"ALTER TABLE appointments ADD COLUMN {column_name} {column_type}")

    cursor.execute("""
        UPDATE appointments
        SET client_name_snapshot = COALESCE(client_name_snapshot, client_name)
        WHERE client_name_snapshot IS NULL
    """)
    cursor.execute("""
        UPDATE appointments
        SET service_name_snapshot = COALESCE(service_name_snapshot, service_name)
        WHERE service_name_snapshot IS NULL
    """)
    cursor.execute("""
        UPDATE appointments
        SET status = COALESCE(status, 'booked')
        WHERE status IS NULL OR status = ''
    """)
    cursor.execute("""
        UPDATE appointments
        SET created_at = COALESCE(created_at, start_time),
            updated_at = COALESCE(updated_at, start_time)
        WHERE created_at IS NULL OR updated_at IS NULL
    """)
    cursor.execute("""
        UPDATE appointments
        SET service_id = (
            SELECT s.id
            FROM services s
            WHERE LOWER(s.name) = LOWER(appointments.service_name)
            LIMIT 1
        )
        WHERE service_id IS NULL AND service_name IS NOT NULL
    """)


def _migrate_clients_schema(cursor: sqlite3.Cursor) -> None:
    """Backfill client links from existing appointment rows."""
    if not _column_exists(cursor, "appointments", "client_id"):
        return

    cursor.execute("""
        INSERT INTO clients (name, created_at, updated_at, marketing_opt_in)
        SELECT
            src.client_name,
            MIN(src.created_value),
            MIN(src.updated_value),
            0
        FROM (
            SELECT
                COALESCE(client_name_snapshot, client_name) AS client_name,
                COALESCE(created_at, start_time, CURRENT_TIMESTAMP) AS created_value,
                COALESCE(updated_at, start_time, CURRENT_TIMESTAMP) AS updated_value
            FROM appointments
            WHERE COALESCE(client_name_snapshot, client_name) IS NOT NULL
              AND TRIM(COALESCE(client_name_snapshot, client_name)) != ''
        ) src
        WHERE NOT EXISTS (
            SELECT 1
            FROM clients c
            WHERE LOWER(c.name) = LOWER(src.client_name)
        )
        GROUP BY LOWER(src.client_name)
    """)

    cursor.execute("""
        WITH duplicates AS (
            SELECT
                MIN(id) AS keep_id,
                LOWER(name) AS normalized_name
            FROM clients
            GROUP BY LOWER(name)
            HAVING COUNT(*) > 1
        )
        UPDATE appointments
        SET client_id = (
            SELECT d.keep_id
            FROM duplicates d
            JOIN clients c ON LOWER(c.name) = d.normalized_name
            WHERE c.id = appointments.client_id
            LIMIT 1
        )
        WHERE client_id IN (
            SELECT c.id
            FROM clients c
            JOIN duplicates d ON LOWER(c.name) = d.normalized_name
            WHERE c.id != d.keep_id
        )
    """)

    cursor.execute("""
        DELETE FROM clients
        WHERE id IN (
            SELECT c.id
            FROM clients c
            JOIN (
                SELECT MIN(id) AS keep_id, LOWER(name) AS normalized_name
                FROM clients
                GROUP BY LOWER(name)
                HAVING COUNT(*) > 1
            ) d
            ON LOWER(c.name) = d.normalized_name
            WHERE c.id != d.keep_id
        )
    """)

    cursor.execute("""
        UPDATE appointments
        SET client_id = (
            SELECT c.id
            FROM clients c
            WHERE LOWER(c.name) = LOWER(COALESCE(appointments.client_name_snapshot, appointments.client_name))
            LIMIT 1
        )
        WHERE client_id IS NULL
          AND COALESCE(client_name_snapshot, client_name) IS NOT NULL
    """)


def get_db_connection() -> sqlite3.Connection:
    """
    Create and return a connection to the SQLite database.
    """
    try:
        logger.info(f"Using SQLite DB: {os.path.abspath(DB_FILE)}")
        logger.info(f"Current working directory: {os.getcwd()}")
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        logger.error(f"Database connection error: {e}")
        raise


def init_database() -> None:
    """
    Initialize the database by creating the appointments table if it doesn't exist.
    
    Table schema:
        - id: INTEGER PRIMARY KEY (auto-increment)
        - client_name: TEXT (name of the client)
        - service_name: TEXT (type of service)
        - start_time: TEXT (YYYY-MM-DD HH:MM format)
        - end_time: TEXT (YYYY-MM-DD HH:MM format)
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Appointments table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS appointments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_name TEXT NOT NULL,
                service_name TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL
            )
        """)

        # Clients table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                name TEXT NOT NULL,
                phone TEXT,
                email TEXT,
                birthday TEXT,
                notes TEXT,
                marketing_opt_in INTEGER NOT NULL DEFAULT 0,
                preferred_stylist_id INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_visit_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (preferred_stylist_id) REFERENCES stylists (id)
            )
        """)
        
        # Users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('client', 'stylist', 'admin')),
                created_at TEXT NOT NULL
            )
        """)
        
        # Stylists table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stylists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                bio TEXT,
                experience_years INTEGER,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)
        
        # Services table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS services (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                category TEXT,
                description TEXT,
                created_at TEXT NOT NULL
            )
        """)
        
        # Stylist services table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stylist_services (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stylist_id INTEGER NOT NULL,
                service_id INTEGER NOT NULL,
                duration INTEGER NOT NULL,
                price REAL,
                buffer_time INTEGER DEFAULT 0,
                FOREIGN KEY (stylist_id) REFERENCES stylists (id),
                FOREIGN KEY (service_id) REFERENCES services (id)
            )
        """)

        # Run migrations only after dependent tables exist.
        _migrate_appointments_schema(cursor)
        _migrate_clients_schema(cursor)
        
        # Conversations table for conversation memory
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE,
                context_json TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create index on start_time to improve performance for date-based queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_start_time
            ON appointments(start_time)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_appointments_stylist_start
            ON appointments(stylist_id, start_time)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_appointments_service
            ON appointments(service_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_appointments_client
            ON appointments(client_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_clients_user_id
            ON clients(user_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_clients_phone
            ON clients(phone)
        """)
        
        conn.commit()
        logger.info(f"Database initialized successfully: {DB_FILE}")
    except sqlite3.Error as e:
        logger.error(f"Database initialization error: {e}")
        raise
    finally:
        conn.close()


def get_appointments_for_day(date: str) -> List[Dict[str, str]]:
    """
    Retrieve all appointments for a given date from the database.
    
    Args:
        date (str): Date in YYYY-MM-DD format (e.g., "2026-03-12")
        
    Returns:
        List[Dict[str, str]]: List of appointments in scheduler format.
        Each appointment has "start" and "end" keys with times in YYYY-MM-DD HH:MM format.
        
    Example:
        >>> appointments = get_appointments_for_day("2026-03-12")
        >>> print(appointments)
        [
            {"start": "2026-03-12 10:00", "end": "2026-03-12 11:00"},
            {"start": "2026-03-12 13:00", "end": "2026-03-12 14:00"}
        ]
        
    Note:
        Returns appointments sorted by start_time in ascending order.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Query appointments for the given date
        query = """
            SELECT start_time, end_time
            FROM appointments
            WHERE DATE(start_time) = ?
            ORDER BY start_time ASC
        """
        
        cursor.execute(query, (date,))
        rows = cursor.fetchall()
        
        # Convert to scheduler format
        appointments = [
            {
                "start": row["start_time"],
                "end": row["end_time"]
            }
            for row in rows
        ]
        
        return appointments
        
    except sqlite3.Error as e:
        logger.error(f"Database query error: {e}")
        raise
    finally:
        conn.close()


def add_appointment(
    client_name: str,
    service_name: str,
    start_time: str,
    end_time: str,
    client_id: int = None,
    client_user_id: int = None,
    stylist_id: int = None,
    service_id: int = None,
    notes: str = None,
    status: str = "booked",
) -> int:
    """
    Add a new appointment to the database.
    
    Args:
        client_name (str): Name of the client
        service_name (str): Type of service (e.g., "Manicure", "Pedicure")
        start_time (str): Start time in YYYY-MM-DD HH:MM format
        end_time (str): End time in YYYY-MM-DD HH:MM format
        
    Returns:
        int: ID of the newly inserted appointment
        
    Example:
        >>> appointment_id = add_appointment(
        ...     "John Doe",
        ...     "Manicure",
        ...     "2026-03-12 10:00",
        ...     "2026-03-12 11:00"
        ... )
        >>> print(f"Created appointment with ID: {appointment_id}")
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO appointments (
                client_name,
                service_name,
                start_time,
                end_time,
                client_id,
                client_user_id,
                stylist_id,
                service_id,
                client_name_snapshot,
                service_name_snapshot,
                status,
                notes,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            client_name,
            service_name,
            start_time,
            end_time,
            client_id,
            client_user_id,
            stylist_id,
            service_id,
            client_name,
            service_name,
            status,
            notes,
            datetime.now().isoformat(),
            datetime.now().isoformat(),
        ))
        
        conn.commit()
        appointment_id = cursor.lastrowid
        
        return appointment_id
        
    except sqlite3.Error as e:
        logger.error(f"Error adding appointment: {e}")
        raise
    finally:
        conn.close()


def get_appointment(appointment_id: int) -> Dict:
    """
    Retrieve a single appointment by ID.
    
    Args:
        appointment_id (int): The ID of the appointment to retrieve
        
    Returns:
        Dict: Appointment details with keys: id, client_name, service_name, start_time, end_time
        Returns empty dict if appointment not found.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT
                id,
                client_name,
                service_name,
                start_time,
                end_time,
                client_id,
                client_user_id,
                stylist_id,
                service_id,
                client_name_snapshot,
                service_name_snapshot,
                status,
                notes,
                created_at,
                updated_at
            FROM appointments
            WHERE id = ?
        """, (appointment_id,))
        
        row = cursor.fetchone()
        
        if row:
            return dict(row)
        return {}
        
    except sqlite3.Error as e:
        logger.error(f"Error retrieving appointment: {e}")
        raise
    finally:
        conn.close()


def delete_appointment(appointment_id: int) -> bool:
    """
    Delete an appointment from the database.
    
    Args:
        appointment_id (int): The ID of the appointment to delete
        
    Returns:
        bool: True if appointment was deleted, False if not found
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("DELETE FROM appointments WHERE id = ?", (appointment_id,))
        conn.commit()
        
        return cursor.rowcount > 0
        
    except sqlite3.Error as e:
        logger.error(f"Error deleting appointment: {e}")
        raise
    finally:
        conn.close()


def get_all_appointments() -> List[Dict]:
    """
    Retrieve all appointments from the database.
    
    Returns:
        List[Dict]: All appointments sorted by start_time
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT
                id,
                client_name,
                service_name,
                start_time,
                end_time,
                client_id,
                client_user_id,
                stylist_id,
                service_id,
                client_name_snapshot,
                service_name_snapshot,
                status,
                notes,
                created_at,
                updated_at
            FROM appointments
            ORDER BY start_time ASC
        """)
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
        
    except sqlite3.Error as e:
        logger.error(f"Error retrieving appointments: {e}")
        raise
    finally:
        conn.close()


def clear_all_appointments() -> int:
    """
    Delete all appointments from the database.
    
    Returns:
        int: Number of appointments deleted
        
    Warning:
        This operation cannot be undone!
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("DELETE FROM appointments")
        conn.commit()
        
        return cursor.rowcount
        
    except sqlite3.Error as e:
        logger.error(f"Error clearing appointments: {e}")
        raise
    finally:
        conn.close()


def insert_user(name: str, phone: str, password_hash: str, role: str) -> int:
    """
    Insert a new user into the database.
    
    Args:
        name (str): User's name
        phone (str): User's phone number (unique)
        password_hash (str): Hashed password
        role (str): User role ('client', 'stylist', 'admin')
        
    Returns:
        int: User ID of the newly inserted user
        
    Raises:
        sqlite3.IntegrityError: If phone number already exists
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        normalized_phone = normalize_phone(phone)
        created_at = datetime.now().isoformat()
        cursor.execute("""
            INSERT INTO users (name, phone, password_hash, role, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (name, normalized_phone, password_hash, role, created_at))
        
        conn.commit()
        return cursor.lastrowid
        
    except sqlite3.Error as e:
        logger.error(f"Error inserting user: {e}")
        raise
    finally:
        conn.close()


def upsert_client(
    name: str,
    user_id: int = None,
    phone: str = None,
    email: str = None,
    birthday: str = None,
    notes: str = None,
    marketing_opt_in: bool = False,
    preferred_stylist_id: int = None,
) -> int:
    """Create or update a client record and return the client ID."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        normalized_name = (name or "").strip()
        if not normalized_name:
            raise ValueError("Client name is required")
        normalized_phone = normalize_phone(phone) if phone else None

        existing = None
        if user_id is not None:
            cursor.execute("SELECT id FROM clients WHERE user_id = ?", (user_id,))
            existing = cursor.fetchone()
        if existing is None and normalized_phone:
            cursor.execute("SELECT id FROM clients WHERE phone = ?", (normalized_phone,))
            existing = cursor.fetchone()
        if existing is None:
            cursor.execute("SELECT id FROM clients WHERE LOWER(name) = LOWER(?)", (normalized_name,))
            existing = cursor.fetchone()

        timestamp = datetime.now().isoformat()
        if existing:
            client_id = existing["id"]
            cursor.execute("""
                UPDATE clients
                SET
                    user_id = COALESCE(?, user_id),
                    name = ?,
                    phone = COALESCE(?, phone),
                    email = COALESCE(?, email),
                    birthday = COALESCE(?, birthday),
                    notes = COALESCE(?, notes),
                    marketing_opt_in = COALESCE(?, marketing_opt_in),
                    preferred_stylist_id = COALESCE(?, preferred_stylist_id),
                    updated_at = ?
                WHERE id = ?
            """, (
                user_id,
                normalized_name,
                normalized_phone,
                email,
                birthday,
                notes,
                1 if marketing_opt_in else None,
                preferred_stylist_id,
                timestamp,
                client_id,
            ))
        else:
            cursor.execute("""
                INSERT INTO clients (
                    user_id,
                    name,
                    phone,
                    email,
                    birthday,
                    notes,
                    marketing_opt_in,
                    preferred_stylist_id,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                normalized_name,
                normalized_phone,
                email,
                birthday,
                notes,
                1 if marketing_opt_in else 0,
                preferred_stylist_id,
                timestamp,
                timestamp,
            ))
            client_id = cursor.lastrowid

        conn.commit()
        return client_id

    except sqlite3.Error as e:
        logger.error(f"Error upserting client: {e}")
        raise
    finally:
        conn.close()


def get_all_clients() -> List[Dict]:
    """Retrieve all clients with their profile details."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT
                c.id,
                c.user_id,
                c.name,
                c.phone,
                c.email,
                c.birthday,
                c.notes,
                c.marketing_opt_in,
                c.preferred_stylist_id,
                c.created_at,
                c.updated_at,
                c.last_visit_at
            FROM clients c
            ORDER BY c.name ASC
        """)
        return [dict(row) for row in cursor.fetchall()]

    except sqlite3.Error as e:
        logger.error(f"Error retrieving clients: {e}")
        raise
    finally:
        conn.close()


def get_client_by_phone(phone: str) -> Dict:
    """Retrieve a client by phone number."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        normalized_phone = normalize_phone(phone)
        cursor.execute("""
            SELECT
                id,
                user_id,
                name,
                phone,
                email,
                birthday,
                notes,
                marketing_opt_in,
                preferred_stylist_id,
                created_at,
                updated_at,
                last_visit_at
            FROM clients
            WHERE phone = ?
            LIMIT 1
        """, (normalized_phone,))
        row = cursor.fetchone()
        return dict(row) if row else {}

    except sqlite3.Error as e:
        logger.error(f"Error retrieving client by phone: {e}")
        raise
    finally:
        conn.close()


def get_client_by_name(name: str) -> Dict:
    """Retrieve a client by exact case-insensitive name."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT
                id,
                user_id,
                name,
                phone,
                email,
                birthday,
                notes,
                marketing_opt_in,
                preferred_stylist_id,
                created_at,
                updated_at,
                last_visit_at
            FROM clients
            WHERE LOWER(name) = LOWER(?)
            LIMIT 1
        """, (name,))
        row = cursor.fetchone()
        return dict(row) if row else {}

    except sqlite3.Error as e:
        logger.error(f"Error retrieving client by name: {e}")
        raise
    finally:
        conn.close()


def get_client_history(client_id: int) -> List[Dict]:
    """Retrieve a client's appointment history."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT
                a.id,
                a.client_id,
                a.client_name_snapshot,
                a.service_name_snapshot,
                a.service_id,
                a.stylist_id,
                a.start_time,
                a.end_time,
                a.status,
                a.notes,
                a.created_at,
                a.updated_at
            FROM appointments a
            WHERE a.client_id = ?
            ORDER BY a.start_time DESC
        """, (client_id,))
        return [dict(row) for row in cursor.fetchall()]

    except sqlite3.Error as e:
        logger.error(f"Error retrieving client history: {e}")
        raise
    finally:
        conn.close()


def get_user_by_phone(phone: str) -> Dict:
    """
    Retrieve a user by phone number.
    
    Args:
        phone (str): User's phone number
        
    Returns:
        Dict: User data with keys: id, name, phone, password_hash, role, created_at
        Returns empty dict if user not found
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        normalized_phone = normalize_phone(phone)
        cursor.execute("""
            SELECT id, name, phone, password_hash, role, created_at
            FROM users
            WHERE phone = ?
        """, (normalized_phone,))
        
        row = cursor.fetchone()
        return dict(row) if row else {}
        
    except sqlite3.Error as e:
        logger.error(f"Error retrieving user: {e}")
        raise
    finally:
        conn.close()


def insert_service(name: str, category: str, description: str) -> int:
    """
    Insert a new service into the database.
    
    Args:
        name (str): Service name (unique)
        category (str): Service category
        description (str): Service description
        
    Returns:
        int: Service ID of the newly inserted service
                    logger.info(f"Using SQLite DB: {os.path.abspath(DB_FILE)}")
    Raises:
        sqlite3.IntegrityError: If service name already exists
    """
    conn = get_db_connection()
    
    try:
        created_at = datetime.now().isoformat()
        cursor.execute("""
            INSERT INTO services (name, category, description, created_at)
            VALUES (?, ?, ?, ?)
        """, (name, category, description, created_at))
        
        conn.commit()
        return cursor.lastrowid
        
    except sqlite3.Error as e:
        logger.error(f"Error inserting service: {e}")
        raise
    finally:
        conn.close()


def insert_stylist_service(stylist_id: int, service_id: int, duration: int, price: float, buffer_time: int = 0) -> int:
    """
    Insert a new stylist service into the database.
    
    Args:
        stylist_id (int): ID of the stylist
        service_id (int): ID of the service
        duration (int): Duration in minutes
        price (float): Price of the service
        buffer_time (int): Buffer time in minutes (default 0)
        
    Returns:
        int: ID of the newly inserted stylist service
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO stylist_services (stylist_id, service_id, duration, price, buffer_time)
            VALUES (?, ?, ?, ?, ?)
        """, (stylist_id, service_id, duration, price, buffer_time))
        
        conn.commit()
        return cursor.lastrowid
        
    except sqlite3.Error as e:
        logger.error(f"Error inserting stylist service: {e}")
        raise
    finally:
        conn.close()


def insert_stylist(user_id: int, bio: str, experience_years: int) -> int:
    """
    Insert a new stylist into the database.
    
    Args:
        user_id (int): ID of the user (must be a stylist role)
        bio (str): Stylist bio
        experience_years (int): Years of experience
        
    Returns:
        int: ID of the newly inserted stylist
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        created_at = datetime.now().isoformat()
        cursor.execute("""
            INSERT INTO stylists (user_id, bio, experience_years, created_at)
            VALUES (?, ?, ?, ?)
        """, (user_id, bio, experience_years, created_at))
        
        conn.commit()
        return cursor.lastrowid
        
    except sqlite3.Error as e:
        logger.error(f"Error inserting stylist: {e}")
        raise
    finally:
        conn.close()


def create_stylist_profile(user_id: int) -> int:
    """Create an empty stylist profile for a new stylist user.

    Args:
        user_id (int): ID of the stylist user

    Returns:
        int: ID of the newly created stylist record
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO stylists (user_id, bio, experience_years, created_at)
            VALUES (?, '', 0, datetime('now'))
        """, (user_id,))

        conn.commit()
        return cursor.lastrowid

    except sqlite3.Error as e:
        logger.error(f"Error creating stylist profile: {e}")
        raise
    finally:
        conn.close()


def update_stylist_profile(stylist_id: int, bio: str = "", experience_years: int = 0) -> None:
    """Update an existing stylist profile."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        normalized_bio = (bio or "").strip()
        normalized_experience = max(0, int(experience_years or 0))
        cursor.execute("""
            UPDATE stylists
            SET bio = ?, experience_years = ?
            WHERE id = ?
        """, (normalized_bio, normalized_experience, stylist_id))
        if cursor.rowcount == 0:
            raise ValueError(f"Stylist {stylist_id} not found")

        conn.commit()

    except (sqlite3.Error, ValueError) as e:
        logger.error(f"Error updating stylist profile: {e}")
        raise
    finally:
        conn.close()


def get_service_by_name(name: str) -> Dict:
    """Retrieve a service by name.

    Args:
        name (str): Service name
        
    Returns:
        Dict: Service data with keys: id, name, category, description, created_at
        Returns empty dict if service not found
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT id, name, category, description, created_at
            FROM services
            WHERE name = ?
        """, (name,))
        
        row = cursor.fetchone()
        return dict(row) if row else {}
        
    except sqlite3.Error as e:
        logger.error(f"Error retrieving service: {e}")
        raise
    finally:
        conn.close()


def get_all_services() -> List[Dict]:
    """Retrieve all services from the database.

    Returns:
        List[Dict]: List of services with keys: id, name, category, description, created_at
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT DISTINCT name, MIN(id) as id, MIN(category) as category, MIN(description) as description, MIN(created_at) as created_at
            FROM services
            GROUP BY name
            ORDER BY name ASC
        """)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    except sqlite3.Error as e:
        logger.error(f"Error retrieving services: {e}")
        raise
    finally:
        conn.close()


def get_all_stylists() -> List[Dict]:
    """Retrieve all stylists with their user information.

    Returns:
        List[Dict]: List of stylists with keys: id, user_id, name, bio, experience_years, created_at
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT DISTINCT u.name, MIN(s.id) as id, MIN(s.user_id) as user_id, MIN(s.bio) as bio, MIN(s.experience_years) as experience_years, MIN(s.created_at) as created_at
            FROM stylists s
            JOIN users u ON s.user_id = u.id
            GROUP BY u.name
            ORDER BY u.name ASC
        """)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    except sqlite3.Error as e:
        logger.error(f"Error retrieving stylists: {e}")
        raise
    finally:
        conn.close()


def get_stylist_by_id(stylist_id: int) -> Dict:
    """Retrieve a stylist by ID with the associated display name."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT s.id, s.user_id, u.name, s.bio, s.experience_years, s.created_at
            FROM stylists s
            JOIN users u ON s.user_id = u.id
            WHERE s.id = ?
            LIMIT 1
        """, (stylist_id,))
        row = cursor.fetchone()
        return dict(row) if row else {}

    except sqlite3.Error as e:
        logger.error(f"Error retrieving stylist by id: {e}")
        raise
    finally:
        conn.close()


def get_stylist_by_phone(phone: str) -> Dict:
    """Retrieve a stylist by phone number with joined user profile data."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        normalized_phone = normalize_phone(phone)
        cursor.execute("""
            SELECT s.id, s.user_id, u.name, u.phone, s.bio, s.experience_years, s.created_at
            FROM stylists s
            JOIN users u ON s.user_id = u.id
            WHERE u.phone = ?
            LIMIT 1
        """, (normalized_phone,))
        row = cursor.fetchone()
        return dict(row) if row else {}

    except sqlite3.Error as e:
        logger.error(f"Error retrieving stylist by phone: {e}")
        raise
    finally:
        conn.close()


def get_services_for_stylist(stylist_id: int) -> List[Dict]:
    """Retrieve services offered by a specific stylist.

    Args:
        stylist_id (int): The stylist's ID

    Returns:
        List[Dict]: List of services with keys: service_id, name, duration, price, buffer_time
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT ss.service_id, s.name, ss.duration, ss.price, ss.buffer_time
            FROM stylist_services ss
            JOIN services s ON ss.service_id = s.id
            WHERE ss.stylist_id = ?
            ORDER BY s.name ASC
        """, (stylist_id,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    except sqlite3.Error as e:
        logger.error(f"Error retrieving stylist services: {e}")
        raise
    finally:
        conn.close()


def get_service_by_id(service_id: int) -> Dict:
    """
    Retrieve a service by ID.
    
    Args:
        service_id (int): Service ID
        
    Returns:
        Dict: Service data with keys: id, name, category, description, created_at
        Returns empty dict if service not found
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT id, name, category, description, created_at
            FROM services
            WHERE id = ?
        """, (service_id,))
        
        row = cursor.fetchone()
        return dict(row) if row else {}
        
    except sqlite3.Error as e:
        logger.error(f"Error retrieving service: {e}")
        raise
    finally:
        conn.close()


def create_service(name: str, category: str = None, description: str = None) -> int:
    """
    Create a new service in the database.
    
    Args:
        name (str): Service name (unique)
        category (str): Service category (optional)
        description (str): Service description (optional)
        
    Returns:
        int: Service ID of the newly created service
        
    Raises:
        sqlite3.IntegrityError: If service name already exists
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        created_at = datetime.now().isoformat()
        cursor.execute("""
            INSERT INTO services (name, category, description, created_at)
            VALUES (?, ?, ?, ?)
        """, (name, category, description, created_at))
        
        conn.commit()
        return cursor.lastrowid
        
    except sqlite3.Error as e:
        logger.error(f"Error creating service: {e}")
        raise
    finally:
        conn.close()


def create_stylist_service(stylist_id: int, service_id: int, duration: int, price: float = None, buffer_time: int = 0) -> int:
    """
    Create a stylist service record.
    
    Args:
        stylist_id (int): ID of the stylist
        service_id (int): ID of the service
        duration (int): Duration in minutes
        price (float): Price (optional)
        buffer_time (int): Buffer time in minutes (default 0)
        
    Returns:
        int: ID of the newly created stylist service record
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO stylist_services (stylist_id, service_id, duration, price, buffer_time)
            VALUES (?, ?, ?, ?, ?)
        """, (stylist_id, service_id, duration, price, buffer_time))
        
        conn.commit()
        return cursor.lastrowid
        
    except sqlite3.Error as e:
        logger.error(f"Error creating stylist service: {e}")
        raise
    finally:
        conn.close()


def create_appointment_if_available(
    client_name: str,
    service_name: str,
    start_time: str,
    end_time: str,
    service_duration: int,
    working_hours: Dict[str, str],
    min_service_duration: int,
    date: str,
    client_id: int = None,
    client_user_id: int = None,
    stylist_id: int = None,
    service_id: int = None,
    client_phone: str = None,
    client_email: str = None,
    notes: str = None,
) -> Dict:
    """
    Create an appointment ONLY if the requested time slot is available.
    
    This function validates that the requested appointment time is a valid,
    available slot before inserting it into the database. It follows a strict
    validation process to ensure data integrity and prevent double-bookings.
    
    Args:
        client_name (str): Name of the client
        service_name (str): Type of service (e.g., "Manicure", "Pedicure")
        start_time (str): Requested start time in YYYY-MM-DD HH:MM format
        end_time (str): Requested end time in YYYY-MM-DD HH:MM format
        service_duration (int): Duration of service in minutes
        working_hours (Dict[str, str]): Salon operating hours 
            Format: {"start": "HH:MM", "end": "HH:MM"}
            Example: {"start": "09:00", "end": "18:00"}
        min_service_duration (int): Shortest possible service duration in minutes
        date (str): Date for the appointment (YYYY-MM-DD format)
        
    Returns:
        Dict: Result dictionary with the following structure:
            - On success: {"success": True, "appointment_id": int}
            - On failure: {"success": False, "error": str}
        
    Example:
        >>> result = create_appointment_if_available(
        ...     client_name="John Doe",
        ...     service_name="Manicure",
        ...     start_time="2026-03-12 10:00",
        ...     end_time="2026-03-12 11:00",
        ...     service_duration=60,
        ...     working_hours={"start": "09:00", "end": "18:00"},
        ...     min_service_duration=45,
        ...     date="2026-03-12"
        ... )
        >>> result
        {"success": True, "appointment_id": 5}
        
    Logic Flow:
        1. Retrieve existing appointments for the given date
        2. Call scheduler to get all valid available time slots
        3. Check if the requested slot exists in the available slots
        4. If available: insert appointment and return appointment ID
        5. If not available: reject request and return error
    """
    try:
        # STEP 1: Retrieve existing appointments for the given date
        # This ensures we don't double-book by checking current bookings
        existing_appointments = get_appointments_for_day(date)
        
        # STEP 2: Call the scheduler to generate all valid available slots
        # Returns a list of dicts with "start" and "end" keys
        available_slots = get_available_slots(
            appointments=existing_appointments,
            service_duration=service_duration,
            working_hours=working_hours,
            min_service_duration=min_service_duration,
            date=date
        )
        
        # STEP 3: Create a slot dict matching the format from get_available_slots()
        # This allows direct comparison with available slots
        requested_slot = {
            "start": start_time,
            "end": end_time
        }
        
        # STEP 3 (continued): Verify that the requested slot exists in available slots
        slot_is_available = requested_slot in available_slots
        
        if slot_is_available:
            # STEP 4: Requested slot is available - proceed with appointment creation
            # Insert the appointment into the database
            effective_client_id = client_id or upsert_client(
                name=client_name,
                user_id=client_user_id,
                phone=client_phone,
                email=client_email,
                notes=notes,
                preferred_stylist_id=stylist_id,
            )
            appointment_id = add_appointment(
                client_name=client_name,
                service_name=service_name,
                start_time=start_time,
                end_time=end_time,
                client_id=effective_client_id,
                client_user_id=client_user_id,
                stylist_id=stylist_id,
                service_id=service_id,
                notes=notes,
            )

            conn = get_db_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    UPDATE clients
                    SET
                        last_visit_at = ?,
                        updated_at = ?
                    WHERE id = ?
                """, (start_time, datetime.now().isoformat(), effective_client_id))
                conn.commit()
            finally:
                conn.close()
            
            # Return success with the new appointment ID
            return {
                "success": True,
                "appointment_id": appointment_id,
                "client_id": effective_client_id,
            }
        else:
            # STEP 5: Requested slot is NOT available - reject appointment
            # Do not insert into database; return error response
            return {
                "success": False,
                "error": "Requested time slot is not available"
            }
            
    except Exception as e:
        # Handle any unexpected errors from database or scheduler
        error_message = f"Error processing appointment request: {str(e)}"
        logger.error(f"create_appointment_if_available failed: {e}")
        return {
            "success": False,
            "error": error_message
        }


def get_stylist_service(stylist_id: int, service_id: int) -> Dict:
    """
    Retrieve stylist service configuration by stylist and service IDs.
    
    Args:
        stylist_id (int): ID of the stylist
        service_id (int): ID of the service
        
    Returns:
        Dict: Service configuration with keys: duration, buffer_time
        Returns empty dict if stylist does not offer the service
        
    Example:
        >>> config = get_stylist_service(1, 2)
        >>> print(config)
        {"duration": 60, "buffer_time": 15}
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT duration, buffer_time
            FROM stylist_services
            WHERE stylist_id = ?
            AND service_id = ?
        """, (stylist_id, service_id))
        
        row = cursor.fetchone()
        return dict(row) if row else {}
        
    except sqlite3.Error as e:
        logger.error(f"Error retrieving stylist service: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    # Example usage and testing
    print("=" * 70)
    print("SALON DATABASE MODULE - EXAMPLE USAGE")
    print("=" * 70)
    
    # Initialize database
    print("\n1. Initializing database...")
    init_database()
    
    # Clear any existing data
    print("\n2. Clearing existing appointments...")
    deleted = clear_all_appointments()
    print(f"   Deleted {deleted} appointments")
    
    # Add sample appointments
    print("\n3. Adding sample appointments for 2026-03-12...")
    appointments_to_add = [
        ("Alice Johnson", "Manicure", "2026-03-12 10:00", "2026-03-12 11:00"),
        ("Bob Smith", "Pedicure", "2026-03-12 11:15", "2026-03-12 12:15"),
        ("Carol Davis", "Gel Nails", "2026-03-12 13:00", "2026-03-12 14:00"),
        ("David Wilson", "Massage", "2026-03-12 14:30", "2026-03-12 15:30"),
    ]
    
    for client, service, start, end in appointments_to_add:
        appt_id = add_appointment(client, service, start, end)
        print(f"   Added: ID {appt_id} - {client} ({service}) at {start}")
    
    # Retrieve appointments for the day
    print("\n4. Retrieving appointments for 2026-03-12 (scheduler format)...")
    appointments = get_appointments_for_day("2026-03-12")
    print(f"   Found {len(appointments)} appointments:")
    for appt in appointments:
        print(f"   - {appt['start']} to {appt['end']}")
    
    # Retrieve all appointments with details
    print("\n5. All appointments with full details...")
    all_appts = get_all_appointments()
    for appt in all_appts:
        print(f"   ID {appt['id']}: {appt['client_name']} - {appt['service_name']}")
        print(f"            {appt['start_time']} to {appt['end_time']}")
    
    print("\n" + "=" * 70)
    print("Database module ready for use with scheduler!")
    print("=" * 70)
