from fastapi import APIRouter, Depends, HTTPException, status
from backend.app.schemas.auth import LoginRequest, SignUpRequest, AuthResponse, UserProfile, LoginEventLog
from backend.app.services.auth_service import sign_in_with_email_password, sign_up_with_email_password, log_login_event
from backend.app.core.security import create_access_token, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest):
    result = sign_in_with_email_password(payload.email, payload.password)
    if not result.get("success"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.get("error_message"))
    token = create_access_token({"sub": result.get("email"), "user_id": result.get("user_id")})
    result["access_token"] = token
    return result

@router.post("/signup", response_model=AuthResponse)
def signup(payload: SignUpRequest):
    result = sign_up_with_email_password(payload.email, payload.password)
    if not result.get("success"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.get("error_message"))
    token = create_access_token({"sub": result.get("email"), "user_id": result.get("user_id")})
    result["access_token"] = token
    return result

@router.get("/me", response_model=UserProfile)
def get_me(user: dict = Depends(get_current_user)):
    return {
        "email": user.get("sub", user.get("email", "unknown")),
        "name": user.get("name", "User"),
        "provider": user.get("provider", "email"),
        "user_id": user.get("user_id")
    }

@router.post("/log-event")
def log_event(event: LoginEventLog):
    success = log_login_event(
        user_email=event.email or "unknown",
        provider=event.provider,
        user_name=event.user_name,
        user_id=event.user_id
    )
    return {"status": "logged" if success else "failed"}

