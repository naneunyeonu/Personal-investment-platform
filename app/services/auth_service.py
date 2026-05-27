"""
인증 서비스 레이어

라우터와 DB 로직을 분리하여 테스트 가능성 확보.
"""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_token_type,
)
from app.auth.password import hash_password, verify_password
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
)


async def register_user(db: AsyncSession, req: RegisterRequest) -> User:
    """
    신규 사용자 등록.
    이메일 중복 시 409 반환.
    """
    result = await db.execute(select(User).where(User.email == req.email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user = User(
        email=req.email,
        hashed_password=hash_password(req.password),
        full_name=req.full_name,
        phone_number=req.phone_number,
    )
    db.add(user)
    await db.flush()   # id 확보 (commit은 get_db() 제너레이터에서 처리)
    await db.refresh(user)
    return user


async def login_user(db: AsyncSession, req: LoginRequest) -> TokenResponse:
    """
    이메일 + 비밀번호 검증 후 JWT 쌍 반환.
    실패 시 401 (이메일 존재 여부를 노출하지 않음).
    """
    _invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid email or password",
        headers={"WWW-Authenticate": "Bearer"},
    )

    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(req.password, user.hashed_password):
        raise _invalid
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )

    return TokenResponse(
        access_token=create_access_token(user.id, user.role),
        refresh_token=create_refresh_token(user.id),
    )


async def refresh_tokens(
    db: AsyncSession, refresh_token: str
) -> TokenResponse:
    """
    Refresh Token 검증 후 새 토큰 쌍 발급.
    """
    from jose import JWTError
    import uuid

    _invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired refresh token",
    )
    try:
        payload = decode_token(refresh_token)
        verify_token_type(payload, "refresh")
        user_id = uuid.UUID(payload["sub"])
    except (JWTError, ValueError, KeyError):
        raise _invalid

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise _invalid

    return TokenResponse(
        access_token=create_access_token(user.id, user.role),
        refresh_token=create_refresh_token(user.id),
    )
