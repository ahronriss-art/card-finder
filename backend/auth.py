"""Passwordless email-code login: request a code, verify it, get a session token.

Flow: POST /auth/request-code {email} emails a 6-digit code; POST /auth/verify-code
{email, code} checks it, creates/reuses the account, and returns a session token the
browser stores. Protected routes depend on `current_user`, which resolves that token.
"""
import hashlib
import secrets
from datetime import datetime, timedelta

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import AuthSession, LoginCode, User, get_db

CODE_TTL_MIN = 10
SESSION_TTL_DAYS = 60


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def gen_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


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
