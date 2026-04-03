"""Dashboard authentication: password → signed cookie session."""

import hashlib
import hmac
import os
import time

from fastapi import Request, Response
from fastapi.responses import JSONResponse

_COOKIE_NAME = "rab_session"
_COOKIE_MAX_AGE = 86400

def _get_password() -> str:
    return os.getenv("ADMIN_PASSWORD", "")

def _get_secret() -> str:
    return hashlib.sha256(f"raise-a-bull:{_get_password()}".encode()).hexdigest()

def _sign(timestamp: str) -> str:
    return hmac.new(_get_secret().encode(), timestamp.encode(), hashlib.sha256).hexdigest()[:32]

def create_session_cookie(response: Response) -> None:
    ts = str(int(time.time()))
    token = f"{ts}.{_sign(ts)}"
    response.set_cookie(_COOKIE_NAME, token, max_age=_COOKIE_MAX_AGE, httponly=True, samesite="strict", path="/")

def verify_session(request: Request) -> bool:
    token = request.cookies.get(_COOKIE_NAME)
    if not token or "." not in token:
        return False
    ts, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(sig, _sign(ts)):
        return False
    try:
        if time.time() - int(ts) > _COOKIE_MAX_AGE:
            return False
    except ValueError:
        return False
    return True

async def auth_middleware(request: Request, call_next):
    path = request.url.path
    # Sub-app mounted at /admin/ sees full path: /admin/api/...
    # Match both /api/... (direct) and /admin/api/... (mounted)
    is_api = "/api/" in path
    is_auth = path.endswith("/api/auth")
    if is_api and not is_auth:
        if not verify_session(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        response = await call_next(request)
        create_session_cookie(response)
        return response
    return await call_next(request)

async def login_endpoint(request: Request):
    body = await request.json()
    password = body.get("password", "")
    expected = _get_password()
    if not expected or not hmac.compare_digest(password, expected):
        return JSONResponse({"error": "Invalid password"}, status_code=401)
    response = JSONResponse({"ok": True})
    create_session_cookie(response)
    return response
