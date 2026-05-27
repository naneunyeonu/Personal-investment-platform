"""
Transactions 모델

다중 통화 회계 핵심 설계 원칙
─────────────────────────────
- execution_price : 체결 당시 자산 원래 통화 기준 단가
- currency_code   : 자산 원래 통화 (KRW / USD 등)
- execution_exchange_rate : 체결 시점의 KRW/USD 환율
  → 원화 환산 금액 = execution_price × quantity × execution_exchange_rate
  → 환차익 분리 계산: (매도환율 - 매수환율) × 달러 원금
"""

import uuid
from decimal import Decimal

from sqlalchemy import Enum as PgEnum, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import AssetClass, CurrencyCode, MarketType, TransactionType
from app.db.base import Base, TimestampMixin


class Transaction(Base, TimestampMixin):
    __tablename__ = "transactions"

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
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="감사 추적용 — 포트폴리오 소유자와 일치해야 함",
    )

    # 종목 정보
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    asset_class: Mapped[AssetClass] = mapped_column(
        PgEnum(AssetClass, name="asset_class", create_type=True),
        nullable=False,
    )
    market: Mapped[MarketType] = mapped_column(
        PgEnum(MarketType, name="market_type", create_type=True),
        nullable=False,
    )
    transaction_type: Mapped[TransactionType] = mapped_column(
        PgEnum(TransactionType, name="transaction_type", create_type=True),
        nullable=False,
    )

    # ─── 핵심 다중 통화 회계 컬럼 ────────────────────────────────────────
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(precision=18, scale=8),
        nullable=False,
        comment="체결 수량",
    )
    execution_price: Mapped[Decimal] = mapped_column(
        Numeric(precision=18, scale=4),
        nullable=False,
        comment="체결 단가 (currency_code 기준 원래 통화)",
    )
    currency_code: Mapped[CurrencyCode] = mapped_column(
        PgEnum(CurrencyCode, name="currency_code", create_type=True),
        nullable=False,
        comment="체결 통화 코드 (ISO 4217)",
    )
    execution_exchange_rate: Mapped[Decimal] = mapped_column(
        Numeric(precision=18, scale=6),
        nullable=False,
        comment="체결 시점 원화 환산 환율 (1 USD = N KRW). KRW 자산은 1.0 저장",
    )
    # ──────────────────────────────────────────────────────────────────────

    # 수수료 (거래 통화 기준)
    commission: Mapped[Decimal] = mapped_column(
        Numeric(precision=18, scale=4),
        nullable=False,
        default=Decimal("0"),
    )
    commission_currency: Mapped[CurrencyCode] = mapped_column(
        PgEnum(CurrencyCode, name="currency_code", create_type=True),
        nullable=False,
    )

    # 외부 주문 참조 (KIS API / 브로커 주문 ID)
    broker_order_id: Mapped[str | None] = mapped_column(
        String(100),
        unique=True,
        nullable=True,
        comment="KIS API 또는 외부 브로커 주문 번호",
    )

    notes: Mapped[str | None] = mapped_column(Text)

    # Relationships
    portfolio: Mapped["Portfolio"] = relationship(  # noqa: F821
        "Portfolio",
        back_populates="transactions",
    )

    def krw_total_amount(self) -> Decimal:
        """체결 원화 환산 총액 (수수료 미포함)"""
        return self.execution_price * self.quantity * self.execution_exchange_rate

    def __repr__(self) -> str:
        return (
            f"<Transaction id={self.id} ticker={self.ticker} "
            f"type={self.transaction_type} qty={self.quantity} "
            f"price={self.execution_price} {self.currency_code}>"
        )
