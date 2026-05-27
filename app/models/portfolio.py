"""
Portfolios 모델

- 한 사용자가 여러 포트폴리오를 보유 가능 (예: 성장주 포트폴리오 / 배당주 포트폴리오)
- 포트폴리오 단위로 ML 최적화 및 LLM 분석이 수행됨
"""

import uuid

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Portfolio(Base, TimestampMixin):
    __tablename__ = "portfolios"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    # 포트폴리오 기준 통화 (원화 / 달러 혼합 포트폴리오 지원을 위해 명시)
    base_currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="KRW",
        server_default="KRW",
        comment="ISO 4217 통화 코드 (KRW / USD 등)",
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    # 마지막 ML 최적화 결과 스냅샷 (JSON 직렬화)
    last_optimization_result: Mapped[str | None] = mapped_column(
        Text,
        comment="PyPortfolioOpt / Riskfolio-Lib 최적화 결과 JSON",
    )

    # Relationships
    owner: Mapped["User"] = relationship(  # noqa: F821
        "User",
        back_populates="portfolios",
    )
    holdings: Mapped[list["Holding"]] = relationship(  # noqa: F821
        "Holding",
        back_populates="portfolio",
        cascade="all, delete-orphan",
        lazy="select",
    )
    transactions: Mapped[list["Transaction"]] = relationship(  # noqa: F821
        "Transaction",
        back_populates="portfolio",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<Portfolio id={self.id} name={self.name} owner={self.owner_id}>"
