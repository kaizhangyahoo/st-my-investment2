from typing import Optional
from pydantic import BaseModel

class LoginRequest(BaseModel):
    email: str
    password: str

class SignUpRequest(BaseModel):
    email: str
    password: str


class AuthResponse(BaseModel):
    success: bool
    email: Optional[str] = None
    user_id: Optional[str] = None
    display_name: Optional[str] = None
    id_token: Optional[str] = None
    access_token: Optional[str] = None
    error_message: Optional[str] = None

class UserProfile(BaseModel):
    email: str
    name: Optional[str] = None
    provider: str
    user_id: Optional[str] = None

class LoginEventLog(BaseModel):
    provider: str
    email: Optional[str] = None
    user_name: Optional[str] = None
    user_id: Optional[str] = None
