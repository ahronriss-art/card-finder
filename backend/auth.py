"""Email + password login with long-lived sessions.

Flow: POST /auth/signup {email, password} creates (or claims) the account and
returns a session token; POST /auth/login {email, password} verifies and returns
a token. The browser stores the token and sends it as a Bearer header; the
session is effectively permanent so users stay signed in. Protected routes depend
on `current_user`, which resolves that token.
"""
import hashlib
import secrets
from datetime import datetime, timedelta

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import AuthSession, User, get_db

SESSION_TTL_DAYS = 3650  # ~10 years — stay signed in until they explicitly log out
PBKDF2_ROUNDS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ROUNDS)
    return f"{salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    if not stored or "$" not in stored:
        return False
    salt, h = stored.split("$", 1)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ROUNDS)
    return secrets.compare_digest(dk.hex(), h)


def gen_token() -> str:
    return secrets.token_urlsafe(32)


def norm_email(email: str) -> str:
    return (email or "").strip().lower()


async def current_user(
    authorization: str = Header(None),
    x_auth_token: str = Header(None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve the logged-in user from the session token, or 401."""
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    token = token or x_auth_token
    if not token:
        raise HTTPException(401, "Not signed in")

    r = await db.execute(select(AuthSession).where(AuthSession.token == token))
    sess = r.scalar_one_or_none()
    if not sess or (sess.expires_at and sess.expires_at < datetime.utcnow()):
        raise HTTPException(401, "Session expired — please sign in again")

    r = await db.execute(select(User).where(User.id == sess.user_id))
    user = r.scalar_one_or_none()
    if not user:
        raise HTTPException(401, "Account not found")
    return user


async def issue_session(db: AsyncSession, user_id: int) -> str:
    token = gen_token()
    db.add(AuthSession(
        token=token,
        user_id=user_id,
        expires_at=datetime.utcnow() + timedelta(days=SESSION_TTL_DAYS),
    ))
    await db.commit()
    return token
