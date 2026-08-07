"""Authentication endpoints: register, login, me."""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from backend.database.repositories.user_repo import create_user, get_user_by_email
from backend.services.auth import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(req: RegisterRequest):
    email = req.email.lower()
    if get_user_by_email(email):
        raise HTTPException(status_code=409, detail="Email already registered")

    user_id = uuid.uuid4().hex
    create_user(
        user_id=user_id,
        email=email,
        password_hash=hash_password(req.password),
        full_name=req.full_name,
    )
    token = create_access_token(user_id, email)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {"id": user_id, "email": email, "full_name": req.full_name},
    }


@router.post("/login")
async def login(req: LoginRequest):
    email = req.email.lower()
    user = get_user_by_email(email)
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token(user["id"], email)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {"id": user["id"], "email": user["email"], "full_name": user.get("full_name")},
    }


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return {"user": user}
