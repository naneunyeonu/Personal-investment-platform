"""
Users 모델

- Soft Delete: is_active=False 로 논리 삭제 (물리 DELETE 금지)
- RBAC: UserRole enum 으로 ADMIN / USER 권한 분리
- 비밀번호는 bcrypt 해시로만 저장
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum as PgEnum, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import UserRole
from app.db.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    email: Mapped[str] = mapped_column(
        String(320),
        unique=True,
        nullable=False,
        index=True,
    )
    hashed_password: Mapped[str] = mapped_column(String(256), nullable=False)

    full_name: Mapped[str | None] = mapped_column(String(100))
    phone_number: Mapped[str | None] = mapped_column(String(20))

    role: Mapped[UserRole] = mapped_column(
        PgEnum(UserRole, name="user_role", create_type=True),
        nullable=False,
        default=UserRole.USER,
        server_default=UserRole.USER.value,
    )

    # Soft Delete — ADMIN이 is_active=False 로 전환, 물리 DELETE 사용 금지
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    deactivated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="비활성화를 수행한 ADMIN의 user.id",
    )

    # 선택적 프로필
    investment_profile: Mapped[str | None] = mapped_column(
        Text,
        comment="투자 성향 JSON 직렬화 문자열 (리스크 허용도, 투자 기간 등)",
    )

    # Relationships
    portfolios: Mapped[list["Portfolio"]] = relationship(  # noqa: F821
        "Portfolio",
        back_populates="owner",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email} role={self.role}>"
