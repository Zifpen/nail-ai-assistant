"""
FastAPI application for nail salon booking system.

Provides REST API endpoints for:
- Retrieving available appointment slots
- Creating new appointments with slot validation
- User registration and authentication
"""

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from typing import List, Dict, Optional
from datetime import datetime
import bcrypt
import jwt

# Import database and scheduler functions
from database import (
    get_appointments_for_day, 
    create_appointment_if_available,
    insert_user,
    get_user_by_phone
)
from scheduler import get_available_slots


# ============================================================================
# FastAPI Application Setup
# ============================================================================

app = FastAPI(
    title="Nail Salon Booking System",
    description="API for managing nail salon appointments",
    version="1.0.0"
)


# ============================================================================
# Pydantic Request/Response Models
# ============================================================================

class AvailableSlotsRequest(BaseModel):
    """Request model for available slots endpoint"""
    date: str  # YYYY-MM-DD format
    service_duration: int  # Duration in minutes


class AvailableSlotsResponse(BaseModel):
    """Response model for available slots"""
    date: str
    total_slots: int
    slots: List[Dict[str, str]]


class BookAppointmentRequest(BaseModel):
    """Request model for booking an appointment"""
    client_name: str
    service_name: str
    start_time: str  # YYYY-MM-DD HH:MM format
    end_time: str    # YYYY-MM-DD HH:MM format
    service_duration: int  # Duration in minutes
    date: str  # YYYY-MM-DD format


class BookAppointmentResponse(BaseModel):
    """Response model for booking an appointment"""
    success: bool
    appointment_id: int = None
    error: Optional[str] = None

class RegisterRequest(BaseModel):
    """Request model for user registration"""
    name: str
    phone: str
    password: str
    role: str  # 'client', 'stylist', 'admin'


class RegisterResponse(BaseModel):
    """Response model for user registration"""
    user_id: int
    message: str


class LoginRequest(BaseModel):
    """Request model for user login"""
    phone: str
    password: str


class LoginResponse(BaseModel):
    """Response model for user login"""
    token: str
    user_id: int
    role: str

# ============================================================================
# Configuration Constants
# ============================================================================

# Salon operating hours
WORKING_HOURS = {
    "start": "09:00",
    "end": "18:00"
}

# Minimum service duration (minutes)
MIN_SERVICE_DURATION = 45

# JWT Secret Key (in production, use environment variable)
JWT_SECRET_KEY = "your-secret-key-here"
JWT_ALGORITHM = "HS256"


# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/", tags=["Health"])
def read_root():
    """
    Health check endpoint.
    
    Returns:
        dict: API status message
    """
    return {
        "message": "Nail Salon Booking System API",
        "status": "running"
    }


@app.get(
    "/available-slots",
    response_model=AvailableSlotsResponse,
    tags=["Slots"]
)
def get_available_slots_endpoint(
    date: str = Query(..., description="Date in YYYY-MM-DD format"),
    service_duration: int = Query(..., description="Service duration in minutes")
):
    """
    Get all available appointment slots for a given date and service duration.
    
    This endpoint retrieves existing appointments for the date, then generates
    all valid available time slots that can accommodate the requested service.
    
    Query Parameters:
        - date (str): Appointment date in YYYY-MM-DD format (e.g., "2026-03-12")
        - service_duration (int): Service duration in minutes (e.g., 60)
    
    Returns:
        AvailableSlotsResponse: JSON with date, total slots count, and list of available slots
        
    Example:
        GET /available-slots?date=2026-03-12&service_duration=60
        
        Response:
        {
            "date": "2026-03-12",
            "total_slots": 7,
            "slots": [
                {"start": "2026-03-12 09:00", "end": "2026-03-12 10:00"},
                {"start": "2026-03-12 11:00", "end": "2026-03-12 12:00"}
            ]
        }
    
    Raises:
        HTTPException: If date format is invalid or service_duration is invalid
    """
    try:
        # Validate date format
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid date format. Use YYYY-MM-DD (e.g., 2026-03-12)"
            )
        
        # Validate service_duration
        if service_duration <= 0:
            raise HTTPException(
                status_code=400,
                detail="Service duration must be greater than 0 minutes"
            )
        
        # STEP 1: Retrieve existing appointments for the date
        existing_appointments = get_appointments_for_day(date)
        
        # STEP 2: Get all available slots for this date and service duration
        available_slots = get_available_slots(
            appointments=existing_appointments,
            service_duration=service_duration,
            working_hours=WORKING_HOURS,
            min_service_duration=MIN_SERVICE_DURATION,
            date=date
        )
        
        # STEP 3: Return formatted response
        return AvailableSlotsResponse(
            date=date,
            total_slots=len(available_slots),
            slots=available_slots
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving available slots: {str(e)}"
        )


@app.post(
    "/book",
    response_model=BookAppointmentResponse,
    tags=["Appointments"]
)
def book_appointment(request: BookAppointmentRequest):
    """
    Create a new appointment if the requested time slot is available.
    
    This endpoint validates that the requested appointment time slot is available
    before creating the appointment in the database. If the slot is not available,
    the request is rejected and no appointment is created.
    
    Request Body (JSON):
        {
            "client_name": "Alice Johnson",
            "service_name": "Manicure",
            "start_time": "2026-03-12 10:00",
            "end_time": "2026-03-12 11:00",
            "service_duration": 60,
            "date": "2026-03-12"
        }
    
    Returns:
        BookAppointmentResponse: JSON with success status and appointment ID or error message
        
    Example (Success):
        {
            "success": true,
            "appointment_id": 5,
            "error": null
        }
        
    Example (Failure):
        {
            "success": false,
            "appointment_id": null,
            "error": "Requested time slot is not available"
        }
    
    Raises:
        HTTPException: If request validation fails or server error occurs
    """
    try:
        # Validate date format
        try:
            datetime.strptime(request.date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid date format. Use YYYY-MM-DD (e.g., 2026-03-12)"
            )
        
        # Validate start_time and end_time format
        try:
            datetime.strptime(request.start_time, "%Y-%m-%d %H:%M")
            datetime.strptime(request.end_time, "%Y-%m-%d %H:%M")
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid time format. Use YYYY-MM-DD HH:MM (e.g., 2026-03-12 10:00)"
            )
        
        # Validate required fields
        if not request.client_name or not request.client_name.strip():
            raise HTTPException(
                status_code=400,
                detail="Client name is required"
            )
        
        if not request.service_name or not request.service_name.strip():
            raise HTTPException(
                status_code=400,
                detail="Service name is required"
            )
        
        if request.service_duration <= 0:
            raise HTTPException(
                status_code=400,
                detail="Service duration must be greater than 0 minutes"
            )
        
        # Call create_appointment_if_available with validation
        result = create_appointment_if_available(
            client_name=request.client_name,
            service_name=request.service_name,
            start_time=request.start_time,
            end_time=request.end_time,
            service_duration=request.service_duration,
            working_hours=WORKING_HOURS,
            min_service_duration=MIN_SERVICE_DURATION,
            date=request.date
        )
        
        # Return result from database function
        if result.get("success"):
            return BookAppointmentResponse(
                success=True,
                appointment_id=result.get("appointment_id"),
                error=None
            )
        else:
            return BookAppointmentResponse(
                success=False,
                appointment_id=None,
                error=result.get("error", "Unknown error occurred")
            )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error processing appointment booking: {str(e)}"
        )


@app.post(
    "/register",
    response_model=RegisterResponse,
    tags=["Authentication"]
)
def register_user(request: RegisterRequest):
    """
    Register a new user.
    
    This endpoint creates a new user account with hashed password.
    
    Request Body (JSON):
        {
            "name": "Anna",
            "phone": "1234567890",
            "password": "123456",
            "role": "stylist"
        }
    
    Returns:
        RegisterResponse: JSON with user_id and success message
        
    Raises:
        HTTPException: If validation fails or user already exists
    """
    try:
        # Validate role
        valid_roles = ["client", "stylist", "admin"]
        if request.role not in valid_roles:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid role. Must be one of: {', '.join(valid_roles)}"
            )
        
        # Validate phone format (basic check)
        if not request.phone or len(request.phone) < 10:
            raise HTTPException(
                status_code=400,
                detail="Phone number must be at least 10 digits"
            )
        
        # Hash password
        password_hash = bcrypt.hashpw(request.password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        # Insert user
        user_id = insert_user(
            name=request.name,
            phone=request.phone,
            password_hash=password_hash,
            role=request.role
        )
        
        return RegisterResponse(
            user_id=user_id,
            message=f"User {request.name} registered successfully as {request.role}"
        )
        
    except Exception as e:
        if "UNIQUE constraint failed" in str(e):
            raise HTTPException(
                status_code=400,
                detail="Phone number already registered"
            )
        raise HTTPException(
            status_code=500,
            detail=f"Error registering user: {str(e)}"
        )


@app.post(
    "/login",
    response_model=LoginResponse,
    tags=["Authentication"]
)
def login_user(request: LoginRequest):
    """
    Authenticate a user and return JWT token.
    
    This endpoint verifies user credentials and returns a JWT token.
    
    Request Body (JSON):
        {
            "phone": "1234567890",
            "password": "123456"
        }
    
    Returns:
        LoginResponse: JSON with JWT token, user_id, and role
        
    Raises:
        HTTPException: If credentials are invalid
    """
    try:
        # Get user by phone
        user = get_user_by_phone(request.phone)
        if not user:
            raise HTTPException(
                status_code=401,
                detail="Invalid phone number or password"
            )
        
        # Verify password
        if not bcrypt.checkpw(request.password.encode('utf-8'), user['password_hash'].encode('utf-8')):
            raise HTTPException(
                status_code=401,
                detail="Invalid phone number or password"
            )
        
        # Generate JWT token
        token_payload = {
            "user_id": user['id'],
            "role": user['role']
        }
        token = jwt.encode(token_payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
        
        return LoginResponse(
            token=token,
            user_id=user['id'],
            role=user['role']
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error during login: {str(e)}"
        )


# ============================================================================
# Entry Point
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    # Run the FastAPI application
    # Access the API at: http://localhost:8000
    # API documentation: http://localhost:8000/docs
    print("=" * 70)
    print("Starting Nail Salon Booking System API")
    print("=" * 70)
    print("\nAccess the API at:")
    print("  - Main: http://localhost:8000")
    print("  - Interactive Docs: http://localhost:8000/docs")
    print("  - Alternative Docs: http://localhost:8000/redoc")
    print("\n" + "=" * 70)
    
    uvicorn.run(app, host="0.0.0.0", port=8000)
