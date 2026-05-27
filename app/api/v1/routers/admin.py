"""
관리자 전용 라우터 — RBAC: JWT role=ADMIN 전용 (architecture_plan.md §2.1)

보안 계층:
  모든 엔드포인트에 require_admin Depends 적용.
  JWT 페이로드 role ≠ ADMIN 이면 FastAPI가 403 반환.

엔드포인트:
  GET    /api/v1/admin/users                      — 전체 사용자 목록
  GET    /api/v1/admin/users/{user_id}            — 특정 사용자 조회
  DELETE /api/v1/admin/users/{user_id}            — 논리적 삭제(Soft Delete)
  PATCH  /api/v1/admin/users/{user_id}/reactivate — 재활성화

논리적 삭제 원칙 (DELETE 엔드포인트):
  데이터베이스에서 레코드를 물리적으로 제거하지 않는다.
  is_active = False 로 전환하고 deactivated_at / deactivated_by 를 기록한다.
  포트폴리오 및 거래 이력 데이터는 FK 무결성 보존을 위해 영구 유지된다.
  (architecture_plan.md §2.2)
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_admin
from app.db.session import get_db
from app.models.user import User
from app.schemas.admin import AdminUserResponse, DeactivateResponse
from app.services.admin_service import (
    deactivate_user,
    get_user,
    list_users,
    reactivate_user,
)

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get(
    "/users",
    response_model=list[AdminUserResponse],
    summary="전체 사용자 목록 조회 (관리자 전용)",
    description=(
        "등록된 모든 사용자를 반환합니다. "
        "`is_active` 필터로 활성/비활성 사용자를 분리 조회할 수 있습니다."
    ),
)
async def list_all_users(
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    is_active: bool | None = Query(
        default=None,
        description="True=활성 사용자만, False=퇴출 사용자만, 미입력=전체",
    ),
    skip: int = Query(default=0, ge=0, description="페이지네이션 오프셋"),
    limit: int = Query(default=50, ge=1, le=200, description="최대 반환 개수"),
) -> list[User]:
    return await list_users(db, is_active=is_active, skip=skip, limit=limit)


@router.get(
    "/users/{user_id}",
    response_model=AdminUserResponse,
    summary="특정 사용자 조회 (관리자 전용)",
)
async def get_one_user(
    user_id: uuid.UUID,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    return await get_user(db, user_id)


@router.delete(
    "/users/{user_id}",
    response_model=DeactivateResponse,
    status_code=status.HTTP_200_OK,
    summary="사용자 퇴출 — 논리적 삭제 (관리자 전용)",
    description=(
        "**[중요] 이 엔드포인트는 데이터베이스 레코드를 물리적으로 삭제하지 않습니다.** "
        "`is_active` 플래그를 `False`로 전환하여 로그인 및 서비스 이용을 차단하며, "
        "포트폴리오·거래 이력은 FK 무결성 보존을 위해 영구 유지됩니다. "
        "(architecture_plan.md §2.2)"
    ),
)
async def deactivate(
    user_id: uuid.UUID,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DeactivateResponse:
    user = await deactivate_user(db, user_id, admin)
    return DeactivateResponse(
        message=(
            "User deactivated (soft delete). "
            "Data retained for referential integrity."
        ),
        user_id=user.id,
        deactivated_at=user.deactivated_at,
        deactivated_by=user.deactivated_by,
    )


@router.patch(
    "/users/{user_id}/reactivate",
    response_model=AdminUserResponse,
    summary="사용자 재활성화 (관리자 전용)",
    description="퇴출된 사용자의 계정을 복원합니다. deactivated_at/by 필드가 초기화됩니다.",
)
async def reactivate(
    user_id: uuid.UUID,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    return await reactivate_user(db, user_id, admin)
