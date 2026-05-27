"""
Holdings 모델

- 포트폴리오 내 현재 보유 종목의 집계 스냅샷
- 거래(Transaction) 집계 결과를 반영하여 업데이트됨
"""

import uuid
from decimal import Decimal

from sqlalchemy import Enum as PgEnum, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import AssetClass, CurrencyCode, MarketType
from app.db.base import Base, TimestampMixin


class Holding(Base, TimestampMixin):
    __tablename__ = "holdings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("portfolios.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    ticker: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="거래소 티커 (예: 005930.KS / AAPL)",
    )
    asset_class: Mapped[AssetClass] = mapped_column(
        PgEnum(AssetClass, name="asset_class", create_type=True),
        nullable=False,
    )
    market: Mapped[MarketType] = mapped_column(
        PgEnum(MarketType, name="market_type", create_type=True),
        nullable=False,
    )

    quantity: Mapped[Decimal] = mapped_column(
        Numeric(precision=18, scale=8),
        nullable=False,
        default=Decimal("0"),
    )

    # 평균 매수 단가 — 해당 자산의 원래 통화 기준
    average_cost: Mapped[Decimal] = mapped_column(
        Numeric(precision=18, scale=4),
        nullable=False,
        default=Decimal("0"),
        comment="평균 매수 단가 (원래 통화 기준)",
    )
    currency_code: Mapped[CurrencyCode] = mapped_column(
        PgEnum(CurrencyCode, name="currency_code", create_type=True),
        nullable=False,
    )

    # Relationships
    portfolio: Mapped["Portfolio"] = relationship(  # noqa: F821
        "Portfolio",
        back_populates="holdings",
    )

    def __repr__(self) -> str:
        return (
            f"<Holding ticker={self.ticker} qty={self.quantity} "
            f"portfolio={self.portfolio_id}>"
        )
