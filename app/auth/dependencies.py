"""
FastAPI Depends() 기반 RBAC 의존성

사용 예시:
    @router.get("/admin-only")
    async def admin_route(
        current_user: Annotated[User, Depends(require_admin)]
    ): ...

    @router.get("/my-data")
    async def user_route(
        current_user: Annotated[User, Depends(get_current_active_user)]
    ): ...
"""

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import decode_token, verify_token_type
from app.core.enums import UserRole
from app.db.session import get_db
from app.models.user import User

_bearer = HTTPBearer(auto_error=True)

_CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)
_INACTIVE_EXCEPTION = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="User account is deactivated",
)
_FORBIDDEN_EXCEPTION = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="Insufficient permissions",
)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """JWT 검증 후 User 객체 반환. 비활성 계정 포함."""
    try:
        payload = decode_token(credentials.credentials)
        verify_token_type(payload, "access")
        user_id = uuid.UUID(payload["sub"])
    except (JWTError, ValueError, KeyError):
        raise _CREDENTIALS_EXCEPTION

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise _CREDENTIALS_EXCEPTION
    return user


async def get_current_active_user(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """활성 상태의 USER / ADMIN 모두 허용"""
    if not user.is_active:
        raise _INACTIVE_EXCEPTION
    return user


async def require_admin(
    user: Annotated[User, Depends(get_current_active_user)],
) -> User:
    """ADMIN 역할 전용 엔드포인트"""
    if user.role != UserRole.ADMIN:
        raise _FORBIDDEN_EXCEPTION
    return user
