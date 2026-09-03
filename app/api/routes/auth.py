"""Authentication routes."""

import hmac
from fastapi import APIRouter, HTTPException, Request, Response

from app.config import settings
from app.auth import (
    _hash_password, authenticate, create_oauth_state, create_token,
    exchange_google_code, google_authorization_url, google_is_configured, user_from_token, validate_oauth_state
)
from app.database import create_user, get_user_by_username, link_user_provider
from app.models.requests import LoginRequest, SignupRequest
from app.models.responses import LoginResponse

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/signup", response_model=LoginResponse, status_code=201)
def signup(request: SignupRequest):
    """Create a new user account."""
    email = request.email.strip().lower()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    if email == settings.auth_username.lower() or get_user_by_username(email):
        raise HTTPException(status_code=409, detail="Email already registered")

    salt = settings.auth_secret.encode()[:16].ljust(16, b"0")
    password_hash = _hash_password(request.password, salt)
    user = create_user(
        username=email,
        password_hash=password_hash,
        provider="local",
        provider_subject=None,
        full_name=request.full_name,
        organization=request.organization,
        team_name=request.team_name,
        job_title=request.job_title,
        manager_email=request.manager_email.strip().lower() if request.manager_email else None,
    )
    return LoginResponse(access_token=create_token(subject=user["username"], user_id=user["user_id"]), is_new_user=True)


@router.post("/login", response_model=LoginResponse)
def login(request: LoginRequest):
    """Authenticate user with email/password."""
    token = authenticate(request.email.strip().lower(), request.password)
    if not token:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return LoginResponse(access_token=token)


@router.post("/demo", response_model=LoginResponse)
def demo_login():
    """Instant login for demo evaluation (admin access)."""
    demo_email = "demo.user@docflow.ai"
    user = get_user_by_username(demo_email)
    if user is None:
        user = create_user(
            username=demo_email,
            password_hash=None,
            provider="demo",
            provider_subject="demo-user",
            full_name="Demo User",
            organization="DocFlow Community",
            team_name="Engineering",
            job_title="Product Explorer",
        )
    # Return an admin token so demo users can see all features
    return LoginResponse(access_token=create_token(subject=settings.auth_username, user_id=settings.dev_user_id))


@router.get("/google/start", include_in_schema=False)
def google_start(request: Request, response: Response):
    """Start Google OAuth flow."""
    if not google_is_configured():
        raise HTTPException(status_code=503, detail="Google sign-in is not configured")
    state = create_oauth_state()
    response.set_cookie("google_oauth_state", state, httponly=True, secure=request.url.scheme == "https", samesite="lax", max_age=600)
    response.status_code = 307
    response.headers["location"] = google_authorization_url(state)
    return response


@router.get("/google/callback", include_in_schema=False)
def google_callback(code: str, state: str, request: Request, response: Response):
    """Handle Google OAuth callback."""
    stored_state = request.cookies.get("google_oauth_state")
    if not validate_oauth_state(state) or (stored_state and not hmac.compare_digest(state, stored_state)):
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    try:
        identity = exchange_google_code(code)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    from app.database import get_user_by_provider_subject
    subject = identity["subject"]
    user = get_user_by_provider_subject("google", subject)
    if user is None:
        user = get_user_by_username(identity["email"])
        if user:
            link_user_provider(user["user_id"], "google", subject)
        else:
            user = create_user(
                username=identity["email"],
                password_hash=None,
                provider="google",
                provider_subject=subject,
                full_name=identity.get("name") or "Google User",
                organization="Organization",
                team_name="Team",
                job_title="Role",
            )

    token = create_token(subject=user["username"], user_id=user["user_id"])
    response.delete_cookie("google_oauth_state")
    response.status_code = 307
    response.headers["location"] = f"/?auth_token={token}"
    return response
