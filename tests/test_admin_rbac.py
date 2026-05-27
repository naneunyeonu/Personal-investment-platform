"""
관리자 RBAC 및 Soft Delete 단위 테스트 (architecture_plan.md §2.1 & §2.2)

테스트 범위:
1. RBAC 의존성       — require_admin: ADMIN 허용 / USER 거부 / 비활성 거부
2. JWT 페이로드      — role 필드 포함 여부 및 타입
3. 관리자 서비스     — list_users, get_user, deactivate_user, reactivate_user
4. Soft Delete 보장  — is_active=False 전환, deactivated_at/by 기록, 물리 삭제 없음
5. 전역 is_active 필터 — 비활성 사용자 로그인 차단, refresh 차단
6. 엣지 케이스       — 자기 자신 퇴출 시도, 이중 퇴출, 이중 재활성화
7. 스키마 검증       — AdminUserResponse, DeactivateResponse Pydantic 구조
8. 라우터 구조       — prefix, tags, 임포트 가능성

모두 DB·HTTP 없는 순수 유닛 테스트 (AsyncMock / MagicMock 사용).
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.enums import UserRole


# ─────────────────────────────────────────────────────────────────────────────
# 공통 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

def _make_user(
    *,
    role: UserRole = UserRole.USER,
    is_active: bool = True,
    user_id: uuid.UUID | None = None,
) -> MagicMock:
    """User ORM 객체 mock 생성."""
    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    user.email = f"user_{user.id.hex[:6]}@test.com"
    user.full_name = "테스트 유저"
    user.phone_number = "010-0000-0000"
    user.role = role
    user.is_active = is_active
    user.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    user.deactivated_at = None
    user.deactivated_by = None
    return user


def _make_admin(user_id: uuid.UUID | None = None) -> MagicMock:
    return _make_user(role=UserRole.ADMIN, user_id=user_id)


# ─────────────────────────────────────────────────────────────────────────────
# 1. RBAC 의존성 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestRequireAdminDependency:
    """require_admin Depends 가 role 을 올바르게 검사하는지 확인."""

    @pytest.mark.asyncio
    async def test_admin_user_passes(self):
        """ADMIN 역할 사용자는 통과."""
        from app.auth.dependencies import require_admin
        admin = _make_admin()
        result = await require_admin(admin)
        assert result is admin

    @pytest.mark.asyncio
    async def test_regular_user_raises_403(self):
        """USER 역할은 403 반환."""
        from fastapi import HTTPException
        from app.auth.dependencies import require_admin

        user = _make_user(role=UserRole.USER)
        with pytest.raises(HTTPException) as exc_info:
            await require_admin(user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_inactive_user_blocked_before_role_check(self):
        """비활성 계정은 get_current_active_user 에서 차단됨 (403)."""
        from fastapi import HTTPException
        from app.auth.dependencies import get_current_active_user

        inactive_user = _make_user(is_active=False)
        with pytest.raises(HTTPException) as exc_info:
            await get_current_active_user(inactive_user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_inactive_admin_also_blocked(self):
        """비활성 ADMIN도 차단 (is_active 검사가 role 검사보다 우선)."""
        from fastapi import HTTPException
        from app.auth.dependencies import get_current_active_user

        inactive_admin = _make_admin()
        inactive_admin.is_active = False
        with pytest.raises(HTTPException) as exc_info:
            await get_current_active_user(inactive_admin)
        assert exc_info.value.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
# 2. JWT 페이로드 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestJWTRolePayload:
    """JWT 에 role 필드가 포함되어야 한다 (architecture_plan.md §2.1)."""

    def test_access_token_contains_role(self):
        from app.auth.jwt import create_access_token, decode_token

        admin_id = uuid.uuid4()
        token = create_access_token(admin_id, UserRole.ADMIN)
        payload = decode_token(token)

        assert "role" in payload
        assert payload["role"] == UserRole.ADMIN.value

    def test_user_role_in_token(self):
        from app.auth.jwt import create_access_token, decode_token

        user_id = uuid.uuid4()
        token = create_access_token(user_id, UserRole.USER)
        payload = decode_token(token)
        assert payload["role"] == UserRole.USER.value

    def test_token_type_is_access(self):
        from app.auth.jwt import create_access_token, decode_token

        token = create_access_token(uuid.uuid4(), UserRole.USER)
        payload = decode_token(token)
        assert payload["type"] == "access"

    def test_sub_is_user_id_string(self):
        from app.auth.jwt import create_access_token, decode_token

        uid = uuid.uuid4()
        token = create_access_token(uid, UserRole.ADMIN)
        payload = decode_token(token)
        assert payload["sub"] == str(uid)


# ─────────────────────────────────────────────────────────────────────────────
# 3. 관리자 서비스 — list_users
# ─────────────────────────────────────────────────────────────────────────────

class TestListUsers:
    """admin_service.list_users() 쿼리 분기 검증."""

    @pytest.mark.asyncio
    async def test_list_all_users_no_filter(self):
        """is_active=None 이면 WHERE 절 없이 전체 조회."""
        from app.services.admin_service import list_users

        user1 = _make_user()
        user2 = _make_user(is_active=False)

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [user1, user2]
        db.execute = AsyncMock(return_value=mock_result)

        result = await list_users(db, is_active=None)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_list_active_users_only(self):
        """is_active=True 이면 활성 사용자만 반환."""
        from app.services.admin_service import list_users

        active_user = _make_user(is_active=True)
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [active_user]
        db.execute = AsyncMock(return_value=mock_result)

        result = await list_users(db, is_active=True)
        assert len(result) == 1
        assert result[0].is_active is True

    @pytest.mark.asyncio
    async def test_list_inactive_users_only(self):
        """is_active=False 이면 퇴출 사용자만 반환."""
        from app.services.admin_service import list_users

        inactive = _make_user(is_active=False)
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [inactive]
        db.execute = AsyncMock(return_value=mock_result)

        result = await list_users(db, is_active=False)
        assert len(result) == 1
        assert result[0].is_active is False

    @pytest.mark.asyncio
    async def test_empty_list_returned_if_no_users(self):
        from app.services.admin_service import list_users

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=mock_result)

        result = await list_users(db)
        assert result == []


# ─────────────────────────────────────────────────────────────────────────────
# 4. 관리자 서비스 — get_user
# ─────────────────────────────────────────────────────────────────────────────

class TestGetUser:

    @pytest.mark.asyncio
    async def test_get_existing_user_returns_user(self):
        from app.services.admin_service import get_user

        user = _make_user()
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        db.execute = AsyncMock(return_value=mock_result)

        result = await get_user(db, user.id)
        assert result is user

    @pytest.mark.asyncio
    async def test_get_nonexistent_user_raises_404(self):
        from fastapi import HTTPException
        from app.services.admin_service import get_user

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await get_user(db, uuid.uuid4())
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_inactive_user_still_returns(self):
        """관리자는 비활성 사용자도 조회할 수 있어야 한다."""
        from app.services.admin_service import get_user

        inactive = _make_user(is_active=False)
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = inactive
        db.execute = AsyncMock(return_value=mock_result)

        result = await get_user(db, inactive.id)
        assert result.is_active is False


# ─────────────────────────────────────────────────────────────────────────────
# 5. Soft Delete 보장 — deactivate_user (핵심 테스트)
# ─────────────────────────────────────────────────────────────────────────────

class TestDeactivateUser:
    """
    논리적 삭제(Soft Delete) 정확성 검증.
    [절대 보장] db.delete() 가 절대 호출되지 않아야 한다.
    """

    def _make_db_with_user(self, user: MagicMock) -> AsyncMock:
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        db.execute = AsyncMock(return_value=mock_result)
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_soft_delete_sets_is_active_false(self):
        """is_active 가 False 로 전환되어야 한다."""
        from app.services.admin_service import deactivate_user

        admin = _make_admin()
        target = _make_user()
        db = self._make_db_with_user(target)

        await deactivate_user(db, target.id, admin)

        assert target.is_active is False

    @pytest.mark.asyncio
    async def test_soft_delete_records_deactivated_at(self):
        """deactivated_at 타임스탬프가 기록되어야 한다."""
        from app.services.admin_service import deactivate_user

        admin = _make_admin()
        target = _make_user()
        db = self._make_db_with_user(target)

        await deactivate_user(db, target.id, admin)

        assert target.deactivated_at is not None
        assert isinstance(target.deactivated_at, datetime)

    @pytest.mark.asyncio
    async def test_soft_delete_records_deactivated_by_admin_id(self):
        """deactivated_by 에 관리자 ID 가 기록되어야 한다."""
        from app.services.admin_service import deactivate_user

        admin = _make_admin()
        target = _make_user()
        db = self._make_db_with_user(target)

        await deactivate_user(db, target.id, admin)

        assert target.deactivated_by == admin.id

    @pytest.mark.asyncio
    async def test_physical_delete_never_called(self):
        """
        [핵심 보장] db.delete() 가 절대 호출되지 않아야 한다.
        물리적 DELETE 사용 금지 (architecture_plan.md §2.2).
        """
        from app.services.admin_service import deactivate_user

        admin = _make_admin()
        target = _make_user()
        db = self._make_db_with_user(target)

        await deactivate_user(db, target.id, admin)

        db.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_db_flush_called_after_deactivation(self):
        """변경 사항이 flush 되어야 한다."""
        from app.services.admin_service import deactivate_user

        admin = _make_admin()
        target = _make_user()
        db = self._make_db_with_user(target)

        await deactivate_user(db, target.id, admin)

        db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_cannot_deactivate_self(self):
        """관리자가 자기 자신을 퇴출하려 하면 400 반환."""
        from fastapi import HTTPException
        from app.services.admin_service import deactivate_user

        admin = _make_admin()
        db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await deactivate_user(db, admin.id, admin)
        assert exc_info.value.status_code == 400
        # 쿼리가 실행되지 않아야 한다 (self-check 가 먼저)
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_double_deactivation_raises_409(self):
        """이미 비활성 사용자를 재퇴출하면 409 반환."""
        from fastapi import HTTPException
        from app.services.admin_service import deactivate_user

        admin = _make_admin()
        already_inactive = _make_user(is_active=False)
        db = self._make_db_with_user(already_inactive)

        with pytest.raises(HTTPException) as exc_info:
            await deactivate_user(db, already_inactive.id, admin)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_deactivate_nonexistent_user_raises_404(self):
        """존재하지 않는 사용자 퇴출 시도 → 404."""
        from fastapi import HTTPException
        from app.services.admin_service import deactivate_user

        admin = _make_admin()
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await deactivate_user(db, uuid.uuid4(), admin)
        assert exc_info.value.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# 6. 재활성화 — reactivate_user
# ─────────────────────────────────────────────────────────────────────────────

class TestReactivateUser:

    def _make_db_with_user(self, user: MagicMock) -> AsyncMock:
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        db.execute = AsyncMock(return_value=mock_result)
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_reactivate_sets_is_active_true(self):
        from app.services.admin_service import reactivate_user

        admin = _make_admin()
        inactive = _make_user(is_active=False)
        inactive.deactivated_at = datetime(2026, 3, 1, tzinfo=timezone.utc)
        inactive.deactivated_by = admin.id
        db = self._make_db_with_user(inactive)

        await reactivate_user(db, inactive.id, admin)

        assert inactive.is_active is True

    @pytest.mark.asyncio
    async def test_reactivate_clears_deactivated_fields(self):
        """재활성화 시 deactivated_at / deactivated_by 초기화."""
        from app.services.admin_service import reactivate_user

        admin = _make_admin()
        inactive = _make_user(is_active=False)
        inactive.deactivated_at = datetime(2026, 3, 1, tzinfo=timezone.utc)
        inactive.deactivated_by = admin.id
        db = self._make_db_with_user(inactive)

        await reactivate_user(db, inactive.id, admin)

        assert inactive.deactivated_at is None
        assert inactive.deactivated_by is None

    @pytest.mark.asyncio
    async def test_reactivate_already_active_raises_409(self):
        """이미 활성 사용자를 재활성화하면 409 반환."""
        from fastapi import HTTPException
        from app.services.admin_service import reactivate_user

        admin = _make_admin()
        active = _make_user(is_active=True)
        db = self._make_db_with_user(active)

        with pytest.raises(HTTPException) as exc_info:
            await reactivate_user(db, active.id, admin)
        assert exc_info.value.status_code == 409


# ─────────────────────────────────────────────────────────────────────────────
# 7. 전역 is_active 필터 — 비활성 사용자 차단
# ─────────────────────────────────────────────────────────────────────────────

class TestGlobalIsActiveFilter:
    """
    비활성 사용자가 모든 보호 엔드포인트에 접근하지 못함을 검증.
    인증 레이어(get_current_active_user)가 전역 게이트 역할을 수행.
    """

    @pytest.mark.asyncio
    async def test_inactive_user_blocked_on_login(self):
        """비활성 사용자 로그인 시도 → 403."""
        from fastapi import HTTPException
        from app.services.auth_service import login_user
        from app.schemas.auth import LoginRequest

        inactive = _make_user(is_active=False)
        inactive.hashed_password = "dummy_hash"

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = inactive
        db.execute = AsyncMock(return_value=mock_result)

        req = LoginRequest(email=inactive.email, password="Password1!")
        with patch("app.services.auth_service.verify_password", return_value=True):
            with pytest.raises(HTTPException) as exc_info:
                await login_user(db, req)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_inactive_user_refresh_blocked(self):
        """비활성 사용자 리프레시 토큰 갱신 시도 → 401."""
        from fastapi import HTTPException
        from app.services.auth_service import refresh_tokens
        from app.auth.jwt import create_refresh_token

        inactive = _make_user(is_active=False)
        refresh_token = create_refresh_token(inactive.id)

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = inactive
        db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await refresh_tokens(db, refresh_token)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_active_user_can_login(self):
        """활성 사용자 로그인 성공."""
        from app.services.auth_service import login_user
        from app.schemas.auth import LoginRequest

        active = _make_user(is_active=True)
        active.hashed_password = "dummy_hash"

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = active
        db.execute = AsyncMock(return_value=mock_result)

        req = LoginRequest(email=active.email, password="Password1!")
        with patch("app.services.auth_service.verify_password", return_value=True):
            response = await login_user(db, req)
        assert response.access_token != ""
        assert response.refresh_token != ""

    @pytest.mark.asyncio
    async def test_deactivated_user_blocked_on_active_user_check(self):
        """퇴출 후 get_current_active_user 가 비활성 사용자를 차단."""
        from fastapi import HTTPException
        from app.auth.dependencies import get_current_active_user

        # 퇴출된 사용자 시뮬레이션
        user = _make_user(is_active=False)
        with pytest.raises(HTTPException) as exc_info:
            await get_current_active_user(user)
        assert exc_info.value.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
# 8. 스키마 검증 — AdminUserResponse, DeactivateResponse
# ─────────────────────────────────────────────────────────────────────────────

class TestAdminSchemas:

    def test_admin_user_response_from_attributes(self):
        """from_attributes 모드로 ORM 객체 직렬화."""
        from app.schemas.admin import AdminUserResponse

        user = _make_user(role=UserRole.USER)
        resp = AdminUserResponse.model_validate(user)

        assert resp.id == user.id
        assert resp.email == user.email
        assert resp.role == UserRole.USER
        assert resp.is_active is True
        assert resp.deactivated_at is None
        assert resp.deactivated_by is None

    def test_admin_user_response_includes_deactivated_fields(self):
        """deactivated_at / deactivated_by 필드가 응답에 포함된다."""
        from app.schemas.admin import AdminUserResponse

        admin_id = uuid.uuid4()
        deact_time = datetime(2026, 4, 1, tzinfo=timezone.utc)
        user = _make_user(is_active=False)
        user.deactivated_at = deact_time
        user.deactivated_by = admin_id

        resp = AdminUserResponse.model_validate(user)

        assert resp.is_active is False
        assert resp.deactivated_at == deact_time
        assert resp.deactivated_by == admin_id

    def test_deactivate_response_structure(self):
        """DeactivateResponse 필드 구조 확인."""
        from app.schemas.admin import DeactivateResponse

        uid = uuid.uuid4()
        admin_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        resp = DeactivateResponse(
            message="User deactivated (soft delete). Data retained for referential integrity.",
            user_id=uid,
            deactivated_at=now,
            deactivated_by=admin_id,
        )

        assert resp.user_id == uid
        assert resp.deactivated_by == admin_id
        assert "soft delete" in resp.message.lower() or "deactivated" in resp.message.lower()

    def test_admin_user_response_includes_phone_number(self):
        """AdminUserResponse 는 phone_number 를 포함한다 (일반 UserResponse 와 차이)."""
        from app.schemas.admin import AdminUserResponse

        user = _make_user()
        user.phone_number = "010-1234-5678"
        resp = AdminUserResponse.model_validate(user)
        assert resp.phone_number == "010-1234-5678"


# ─────────────────────────────────────────────────────────────────────────────
# 9. 라우터 구조 검증
# ─────────────────────────────────────────────────────────────────────────────

class TestAdminRouterStructure:

    def test_router_importable(self):
        from app.api.v1.routers.admin import router
        assert router is not None

    def test_router_prefix_is_admin(self):
        from app.api.v1.routers.admin import router
        assert router.prefix == "/admin"

    def test_router_tag_is_admin(self):
        from app.api.v1.routers.admin import router
        assert "Admin" in router.tags

    def test_router_registered_in_main_router(self):
        """admin 라우터가 api_v1_router 에 등록되어 있어야 한다."""
        from app.api.v1.router import api_v1_router
        prefixes = [r.prefix for r in api_v1_router.routes
                    if hasattr(r, "prefix")]
        # include_router 시 routes 에 Mount 또는 APIRoute 등록
        # 라우터 등록 확인 — routes 에서 /admin 경로 포함 여부 체크
        all_paths = [
            getattr(r, "path", "") for r in api_v1_router.routes
        ]
        assert any("/admin" in p for p in all_paths)

    def test_admin_service_importable(self):
        from app.services.admin_service import (
            deactivate_user,
            get_user,
            list_users,
            reactivate_user,
        )
        assert callable(deactivate_user)
        assert callable(get_user)
        assert callable(list_users)
        assert callable(reactivate_user)

    def test_require_admin_dependency_importable(self):
        from app.auth.dependencies import require_admin
        assert callable(require_admin)


# ─────────────────────────────────────────────────────────────────────────────
# 10. 사용자 모델 Soft Delete 필드 구조
# ─────────────────────────────────────────────────────────────────────────────

class TestUserModelSoftDeleteFields:
    """User ORM 모델에 Soft Delete 컬럼이 정의되어 있는지 확인."""

    def test_user_has_is_active_column(self):
        from app.models.user import User
        assert hasattr(User, "is_active")

    def test_user_has_deactivated_at_column(self):
        from app.models.user import User
        assert hasattr(User, "deactivated_at")

    def test_user_has_deactivated_by_column(self):
        from app.models.user import User
        assert hasattr(User, "deactivated_by")

    def test_user_has_role_column(self):
        from app.models.user import User
        assert hasattr(User, "role")

    def test_user_role_enum_has_admin_and_user(self):
        assert UserRole.ADMIN.value == "ADMIN"
        assert UserRole.USER.value == "USER"

    def test_user_default_role_is_user(self):
        """User 기본 역할은 USER 이어야 한다."""
        from app.models.user import User
        col = User.__table__.c.get("role")
        assert col is not None
        assert col.server_default is not None
        # server_default 에 'USER' 포함 확인
        assert "USER" in str(col.server_default.arg)

    def test_user_is_active_default_true(self):
        """is_active 의 기본값은 True 이어야 한다."""
        from app.models.user import User
        col = User.__table__.c.get("is_active")
        assert col is not None
        assert col.server_default is not None
