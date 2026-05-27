"""
인증 라우터
POST /api/v1/auth/register  — 회원가입
POST /api/v1/auth/login     — 로그인 (JWT 발급)
POST /api/v1/auth/refresh   — Access Token 갱신
GET  /api/v1/auth/me        — 내 정보 조회
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_active_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.services.auth_service import login_user, refresh_tokens, register_user

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=201,
    summary="회원가입",
)
async def register(
    req: RegisterRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    return await register_user(db, req)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="로그인 — JWT 발급",
)
async def login(
    req: LoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    return await login_user(db, req)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Access Token 갱신",
)
async def refresh(
    req: RefreshRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    return await refresh_tokens(db, req.refresh_token)


@router.get(
    "/me",
    response_model=UserResponse,
    summary="내 계정 정보 조회",
)
async def me(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> User:
    return current_user
