"""
Transaction 수동 입력 스키마

핵심 제약: 이 플랫폼은 실제 주문 체결을 수행하지 않음.
사용자가 이미 완료된 거래 내역을 '수동으로 기록'하는 용도.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.enums import AssetClass, CurrencyCode, MarketType, TransactionType


class TransactionCreate(BaseModel):
    """
    이미 실행된 거래를 소급 기록하는 스키마.
    실제 매수/매도 실행은 이 플랫폼의 범위 밖.
    """

    ticker: str = Field(min_length=1, max_length=20)
    asset_class: AssetClass
    market: MarketType
    transaction_type: TransactionType

    quantity: Decimal = Field(gt=Decimal("0"))
    execution_price: Decimal = Field(gt=Decimal("0"))
    currency_code: CurrencyCode
    execution_exchange_rate: Decimal = Field(
        gt=Decimal("0"),
        description="체결 시점 환율. KRW 자산은 1.0",
    )

    commission: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    commission_currency: CurrencyCode | None = None
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("ticker")
    @classmethod
    def uppercase_ticker(cls, v: str) -> str:
        return v.upper().strip()

    @model_validator(mode="after")
    def fill_commission_currency(self) -> "TransactionCreate":
        if self.commission_currency is None:
            self.commission_currency = self.currency_code
        return self


class TransactionResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    portfolio_id: uuid.UUID
    ticker: str
    asset_class: AssetClass
    market: MarketType
    transaction_type: TransactionType
    quantity: Decimal
    execution_price: Decimal
    currency_code: CurrencyCode
    execution_exchange_rate: Decimal
    commission: Decimal
    commission_currency: CurrencyCode
    notes: str | None
    created_at: datetime
    updated_at: datetime

    @property
    def krw_total_amount(self) -> Decimal:
        """원화 환산 총액 (수수료 미포함)"""
        return self.execution_price * self.quantity * self.execution_exchange_rate
