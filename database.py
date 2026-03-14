"""
Database layer for nail salon appointment system.

Retrieves appointment data from SQLite and provides it in the format
expected by the scheduler module.
"""

import sqlite3
from typing import List, Dict
from datetime import datetime

# Import scheduler for slot validation
from scheduler import get_available_slots


# Database configuration
DB_FILE = "salon.db"


def get_db_connection() -> sqlite3.Connection:
    """
    Create and return a connection to the SQLite database.
    
    Returns:
        sqlite3.Connection: Connection to the salon.db database
        
    Note:
        Uses sqlite3.Row factory for dict-like row access.
    """
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        print(f"Database connection error: {e}")
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
        
        # Create index on start_time to improve performance for date-based queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_start_time
            ON appointments(start_time)
        """)
        
        conn.commit()
        print(f"Database initialized successfully: {DB_FILE}")
    except sqlite3.Error as e:
        print(f"Database initialization error: {e}")
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
        print(f"Database query error: {e}")
        raise
    finally:
        conn.close()


def add_appointment(
    client_name: str,
    service_name: str,
    start_time: str,
    end_time: str
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
            INSERT INTO appointments (client_name, service_name, start_time, end_time)
            VALUES (?, ?, ?, ?)
        """, (client_name, service_name, start_time, end_time))
        
        conn.commit()
        appointment_id = cursor.lastrowid
        
        return appointment_id
        
    except sqlite3.Error as e:
        print(f"Error adding appointment: {e}")
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
            SELECT id, client_name, service_name, start_time, end_time
            FROM appointments
            WHERE id = ?
        """, (appointment_id,))
        
        row = cursor.fetchone()
        
        if row:
            return dict(row)
        return {}
        
    except sqlite3.Error as e:
        print(f"Error retrieving appointment: {e}")
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
        print(f"Error deleting appointment: {e}")
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
            SELECT id, client_name, service_name, start_time, end_time
            FROM appointments
            ORDER BY start_time ASC
        """)
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
        
    except sqlite3.Error as e:
        print(f"Error retrieving appointments: {e}")
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
        print(f"Error clearing appointments: {e}")
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
        created_at = datetime.now().isoformat()
        cursor.execute("""
            INSERT INTO users (name, phone, password_hash, role, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (name, phone, password_hash, role, created_at))
        
        conn.commit()
        return cursor.lastrowid
        
    except sqlite3.Error as e:
        print(f"Error inserting user: {e}")
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
        cursor.execute("""
            SELECT id, name, phone, password_hash, role, created_at
            FROM users
            WHERE phone = ?
        """, (phone,))
        
        row = cursor.fetchone()
        return dict(row) if row else {}
        
    except sqlite3.Error as e:
        print(f"Error retrieving user: {e}")
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
        print(f"Error inserting service: {e}")
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
        print(f"Error inserting stylist service: {e}")
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
        print(f"Error inserting stylist: {e}")
        raise
    finally:
        conn.close()


def get_service_by_name(name: str) -> Dict:
    """
    Retrieve a service by name.
    
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
        print(f"Error retrieving service: {e}")
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
        print(f"Error retrieving service: {e}")
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
        print(f"Error creating service: {e}")
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
        print(f"Error creating stylist service: {e}")
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
    date: str
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
            appointment_id = add_appointment(
                client_name=client_name,
                service_name=service_name,
                start_time=start_time,
                end_time=end_time
            )
            
            # Return success with the new appointment ID
            return {
                "success": True,
                "appointment_id": appointment_id
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
        print(f"create_appointment_if_available failed: {e}")
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
        print(f"Error retrieving stylist service: {e}")
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
