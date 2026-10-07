"""Authentication endpoints: register, login, me, Google OAuth."""

from __future__ import annotations

import secrets
import uuid
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field

from backend import config
from backend.database.repositories.user_repo import (
    create_user,
    get_or_create_user_by_email,
    get_user_by_email,
)
from backend.services.auth import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_SCOPES = "openid email profile"
_OAUTH_STATE_COOKIE = "ct_oauth_state"


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


# ── Google OAuth (Authorization Code flow) ─────────────────────────────────────

google_router = APIRouter(prefix="/auth/google", tags=["auth"])


@google_router.get("/login")
def google_login():
    if not config.GOOGLE_CLIENT_ID or not config.GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="Google OAuth is not configured")

    state = secrets.token_urlsafe(24)
    params = {
        "client_id": config.GOOGLE_CLIENT_ID,
        "redirect_uri": config.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": GOOGLE_SCOPES,
        "prompt": "select_account",
        "state": state,
    }
    response = RedirectResponse(f"{GOOGLE_AUTH_URL}?{urlencode(params)}")
    response.set_cookie(
        _OAUTH_STATE_COOKIE,
        state,
        max_age=600,
        httponly=True,
        samesite="lax",
    )
    return response


@google_router.get("/callback")
async def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    frontend = config.GOOGLE_FRONTEND_REDIRECT_URI

    if error or not code:
        return RedirectResponse(f"{frontend}?error=google_denied")
    if not state or state != request.cookies.get(_OAUTH_STATE_COOKIE):
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    async with httpx.AsyncClient(timeout=15) as client:
        token_resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": config.GOOGLE_CLIENT_ID,
                "client_secret": config.GOOGLE_CLIENT_SECRET,
                "redirect_uri": config.GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
        if token_resp.status_code != 200:
            return RedirectResponse(f"{frontend}?error=google_token")
        access_token = token_resp.json().get("access_token")

        userinfo_resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if userinfo_resp.status_code != 200:
            return RedirectResponse(f"{frontend}?error=google_userinfo")
        info = userinfo_resp.json()

    email = (info.get("email") or "").lower()
    if not email:
        return RedirectResponse(f"{frontend}?error=google_no_email")

    user = get_or_create_user_by_email(email, info.get("name"))
    token = create_access_token(user["id"], user["email"])

    response = RedirectResponse(f"{frontend}?token={token}")
    response.delete_cookie(_OAUTH_STATE_COOKIE)
    return response
