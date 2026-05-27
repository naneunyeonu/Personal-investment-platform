"""
관리자 전용 Pydantic 스키마 (architecture_plan.md §2.1)

AdminUserResponse  — 관리자가 조회하는 사용자 상세 정보 (deactivated_* 필드 포함)
DeactivateResponse — 논리적 삭제(Soft Delete) 완료 응답
"""

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.core.enums import UserRole


class AdminUserResponse(BaseModel):
    """
    관리자용 사용자 상세 응답.

    일반 UserResponse 와 달리 퇴출 감사 추적 필드
    (deactivated_at, deactivated_by, phone_number) 를 포함한다.
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    email: str
    full_name: str | None
    phone_number: str | None
    role: UserRole
    is_active: bool
    created_at: datetime
    deactivated_at: datetime | None
    deactivated_by: uuid.UUID | None


class DeactivateResponse(BaseModel):
    """
    논리적 삭제 결과 응답.

    DELETE /admin/users/{user_id} 성공 시 반환.
    물리적 레코드가 아닌 is_active 플래그만 변경되었음을 명시한다.
    """

    message: str
    user_id: uuid.UUID
    deactivated_at: datetime
    deactivated_by: uuid.UUID
