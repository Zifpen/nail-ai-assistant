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
    get_user_by_phone,
    get_service_by_name,
    get_service_by_id,
    create_service,
    create_stylist_service,
    create_stylist_profile,
    get_stylist_service,
    get_all_services,
    get_all_stylists,
    get_services_for_stylist
)
from service_resolver import resolve_service_name
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
    client_id: Optional[int] = None
    stylist_id: int
    service_id: int
    client_user_id: Optional[int] = None
    client_phone: Optional[str] = None
    client_email: Optional[str] = None
    notes: Optional[str] = None
    start_time: str  # YYYY-MM-DD HH:MM format
    end_time: str    # YYYY-MM-DD HH:MM format
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


class ServiceItem(BaseModel):
    """Model for a service with duration"""
    name: str
    duration: int


class StylistOnboardingRequest(BaseModel):
    """Request model for stylist service onboarding"""
    stylist_id: int
    services: List[ServiceItem]


class StylistOnboardingResponse(BaseModel):
    """Response model for stylist onboarding"""
    message: str
    services_added: int

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
    stylist_id: int = Query(..., description="Stylist ID"),
    service_id: int = Query(..., description="Service ID")
):
    """
    Get all available appointment slots for a given date, stylist, and service.
    
    This endpoint retrieves the stylist's service configuration, then generates
    all valid available time slots that can accommodate the requested service.
    
    Query Parameters:
        - date (str): Appointment date in YYYY-MM-DD format (e.g., "2026-03-12")
        - stylist_id (int): ID of the stylist
        - service_id (int): ID of the service
    
    Returns:
        AvailableSlotsResponse: JSON with date, total slots count, and list of available slots
        
    Example:
        GET /available-slots?date=2026-03-12&stylist_id=1&service_id=2
        
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
        HTTPException: If date format is invalid or stylist does not offer the service
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
        
        # STEP 1: Retrieve stylist service configuration
        stylist_service = get_stylist_service(stylist_id, service_id)
        
        if not stylist_service:
            raise HTTPException(
                status_code=400,
                detail="Service not offered by this stylist"
            )
        
        # Extract duration from stylist service configuration
        service_duration = stylist_service["duration"]
        
        # STEP 2: Retrieve existing appointments for the date
        existing_appointments = get_appointments_for_day(date)
        
        # STEP 3: Get all available slots for this date and service duration
        available_slots = get_available_slots(
            appointments=existing_appointments,
            service_duration=service_duration,
            working_hours=WORKING_HOURS,
            min_service_duration=MIN_SERVICE_DURATION,
            date=date
        )
        
        requested_date = datetime.strptime(date, "%Y-%m-%d").date()
        now = datetime.now()
        if requested_date == now.date():
            available_slots = [
                slot for slot in available_slots
                if datetime.strptime(slot["start"], "%Y-%m-%d %H:%M") > now
            ]

        # STEP 4: Return formatted response
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
            "stylist_id": 1,
            "service_id": 2,
            "start_time": "2026-03-12 10:00",
            "end_time": "2026-03-12 11:00",
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
            start_dt = datetime.strptime(request.start_time, "%Y-%m-%d %H:%M")
            end_dt = datetime.strptime(request.end_time, "%Y-%m-%d %H:%M")
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid time format. Use YYYY-MM-DD HH:MM (e.g., 2026-03-12 10:00)"
            )

        if start_dt <= datetime.now():
            raise HTTPException(
                status_code=400,
                detail="Cannot book an appointment in the past"
            )
        
        # Validate required fields
        if not request.client_name or not request.client_name.strip():
            raise HTTPException(
                status_code=400,
                detail="Client name is required"
            )
        
        # STEP 1: Retrieve stylist service configuration
        stylist_service = get_stylist_service(request.stylist_id, request.service_id)
        
        if not stylist_service:
            raise HTTPException(
                status_code=400,
                detail="Service not offered by this stylist"
            )
        
        # Extract duration from stylist service configuration
        service_duration = stylist_service["duration"]
        
        # STEP 2: Get service name for database storage
        service_info = get_service_by_id(request.service_id)
        if not service_info:
            raise HTTPException(
                status_code=400,
                detail="Invalid service ID"
            )
        service_name = service_info["name"]
        
        # Call create_appointment_if_available with validation
        result = create_appointment_if_available(
            client_name=request.client_name,
            service_name=service_name,
            start_time=request.start_time,
            end_time=request.end_time,
            service_duration=service_duration,
            working_hours=WORKING_HOURS,
            min_service_duration=MIN_SERVICE_DURATION,
            date=request.date,
            client_id=request.client_id,
            client_user_id=request.client_user_id,
            stylist_id=request.stylist_id,
            service_id=request.service_id,
            client_phone=request.client_phone,
            client_email=request.client_email,
            notes=request.notes,
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

        # If the user is a stylist, create a stylist profile record
        if request.role == "stylist":
            create_stylist_profile(user_id)
        
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


@app.post(
    "/stylist/onboarding/services",
    response_model=StylistOnboardingResponse,
    tags=["Stylist Onboarding"]
)
def stylist_onboarding_services(request: StylistOnboardingRequest):
    """
    Onboard stylist services.
    
    This endpoint allows stylists to configure their offered services.
    It checks if services exist, creates them if needed, and links them to the stylist.
    
    Request Body (JSON):
        {
            "stylist_id": 1,
            "services": [
                {"name": "gel manicure", "duration": 60},
                {"name": "hard gel", "duration": 90}
            ]
        }
    
    Returns:
        StylistOnboardingResponse: Success message and count of services added
        
    Raises:
        HTTPException: If stylist_id is invalid or other errors occur
    """
    try:
        services_added = 0
        
        for service_item in request.services:
            # Resolve stylist-provided service name into a canonical service record
            resolved = resolve_service_name(service_item.name)
            service_id = resolved["service_id"]
            
            # Create stylist service record
            create_stylist_service(
                stylist_id=request.stylist_id,
                service_id=service_id,
                duration=service_item.duration
            )
            
            services_added += 1
        
        return StylistOnboardingResponse(
            message=f"Successfully onboarded {services_added} services for stylist {request.stylist_id}",
            services_added=services_added
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error during stylist onboarding: {str(e)}"
        )


@app.get(
    "/services",
    tags=["Services"]
)
def get_services():
    """
    Get all available services.
    
    Returns:
        List[Dict]: List of services with id and name
    """
    try:
        services = get_all_services()
        return [{"id": s["id"], "name": s["name"]} for s in services]
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving services: {str(e)}"
        )


@app.get(
    "/stylists",
    tags=["Stylists"]
)
def get_stylists():
    """
    Get all stylists.
    
    Returns:
        List[Dict]: List of stylists with id and name
    """
    try:
        stylists = get_all_stylists()
        return [{"id": s["id"], "name": s["name"]} for s in stylists]
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving stylists: {str(e)}"
        )


@app.get(
    "/stylists/{stylist_id}/services",
    tags=["Stylists"]
)
def get_stylist_services(stylist_id: int):
    """
    Get services offered by a specific stylist.
    
    Args:
        stylist_id (int): The stylist's ID
        
    Returns:
        List[Dict]: List of services with service_id, name, duration
    """
    try:
        services = get_services_for_stylist(stylist_id)
        return [{"service_id": s["service_id"], "name": s["name"], "duration": s["duration"]} for s in services]
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving stylist services: {str(e)}"
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
