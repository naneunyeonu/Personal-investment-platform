"""
관리자 서비스 레이어 (architecture_plan.md §2.1 & §2.2)

핵심 제약:
  - deactivate_user(): 물리적 DELETE 사용 절대 금지.
    is_active = False 로의 전환(논리적 삭제)만 허용.
  - 관리자 자신의 계정 비활성화 불가.
  - 비활성 사용자의 포트폴리오·거래내역은 FK 보존을 위해 영구 유지.

사용 흐름:
  POST /admin/users/{id} → deactivate_user()
    ├─ is_active = False
    ├─ deactivated_at = utcnow()
    └─ deactivated_by = admin.id   (감사 추적)
"""

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


# ─────────────────────────────────────────────────────────────────────────────
# 내부 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

async def _get_user_or_404(db: AsyncSession, user_id: uuid.UUID) -> User:
    """사용자 조회. 없으면 404."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return user


# ─────────────────────────────────────────────────────────────────────────────
# 공개 서비스 함수
# ─────────────────────────────────────────────────────────────────────────────

async def list_users(
    db: AsyncSession,
    *,
    is_active: bool | None = None,
    skip: int = 0,
    limit: int = 50,
) -> list[User]:
    """
    전체 사용자 목록 조회 (관리자 전용).

    Args:
        is_active: True → 활성 사용자만, False → 퇴출 사용자만, None → 전체.
        skip: 페이지네이션 오프셋.
        limit: 최대 반환 개수 (최대 200).
    """
    q = select(User)
    if is_active is not None:
        q = q.where(User.is_active == is_active)
    q = q.order_by(User.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    """특정 사용자 조회 (활성·비활성 모두 포함)."""
    return await _get_user_or_404(db, user_id)


async def deactivate_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    admin: User,
) -> User:
    """
    사용자 논리적 삭제 (Soft Delete).

    [절대 금지] DELETE FROM users WHERE id = user_id 사용 불가.
    → 포트폴리오·거래내역 FK 참조 무결성 파괴 방지 (architecture_plan.md §2.2)

    수행 작업:
      1. 관리자 자기 자신 퇴출 시도 → 400 반환
      2. 이미 비활성 → 409 반환
      3. is_active = False, deactivated_at/by 기록 후 flush
    """
    if user_id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate your own account",
        )

    user = await _get_user_or_404(db, user_id)

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is already deactivated",
        )

    # ── 논리적 삭제 — 물리적 DELETE 사용 금지 ─────────────────────────────
    user.is_active = False
    user.deactivated_at = datetime.now(timezone.utc)
    user.deactivated_by = admin.id
    # ──────────────────────────────────────────────────────────────────────

    await db.flush()
    await db.refresh(user)
    return user


async def reactivate_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    admin: User,  # noqa: ARG001  (감사 로그 확장 대비)
) -> User:
    """
    비활성 사용자 재활성화.

    deactivated_at / deactivated_by 를 초기화하여 계정을 복원한다.
    이미 활성 상태면 409 반환.
    """
    user = await _get_user_or_404(db, user_id)

    if user.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is already active",
        )

    user.is_active = True
    user.deactivated_at = None
    user.deactivated_by = None

    await db.flush()
    await db.refresh(user)
    return user
