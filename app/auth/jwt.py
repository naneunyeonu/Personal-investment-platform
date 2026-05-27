"""
JWT 생성 · 검증 유틸리티 (python-jose HS256)

토큰 페이로드 구조:
  sub  : user UUID (str)
  role : UserRole 값 ("ADMIN" | "USER")
  type : "access" | "refresh"
  exp  : 만료 시각 (UTC timestamp)
"""

from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from jose import JWTError, jwt

from app.core.config import settings
from app.core.enums import UserRole

_ALGORITHM = settings.ALGORITHM


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(user_id: UUID, role: UserRole) -> str:
    expire = _utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "role": role.value,
        "type": "access",
        "exp": expire,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=_ALGORITHM)


def create_refresh_token(user_id: UUID) -> str:
    expire = _utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "exp": expire,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=_ALGORITHM)


def decode_token(token: str) -> dict:
    """
    토큰 디코딩 및 서명 검증.
    유효하지 않으면 JWTError 를 raise.
    """
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[_ALGORITHM])


def verify_token_type(
    payload: dict, expected: Literal["access", "refresh"]
) -> None:
    """토큰 타입 불일치 시 ValueError raise"""
    if payload.get("type") != expected:
        raise ValueError(
            f"Invalid token type: expected '{expected}', "
            f"got '{payload.get('type')}'"
        )
