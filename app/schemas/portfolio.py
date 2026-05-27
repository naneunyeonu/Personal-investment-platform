"""
Portfolio / Holding 관련 Pydantic 스키마

핵심 제약: 이 플랫폼은 실제 매수/매도 실행 기능이 없음.
Holdings는 사용자가 '직접 수동 입력'하는 보유 내역 기록임.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.core.enums import AssetClass, CurrencyCode, MarketType


# ─────────────────────────────────────────────────────────────────────────────
# Portfolio
# ─────────────────────────────────────────────────────────────────────────────

class PortfolioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    base_currency: CurrencyCode = CurrencyCode.KRW


class PortfolioUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    base_currency: CurrencyCode | None = None


class PortfolioResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    description: str | None
    base_currency: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# Holding  (수동 입력 보유 종목)
# ─────────────────────────────────────────────────────────────────────────────

class HoldingCreate(BaseModel):
    """
    사용자가 직접 입력하는 보유 종목 등록 스키마.

    주의: execution_exchange_rate는 매수 당시 환율을 사용자가 직접 기입.
          KRW 자산이면 1.0 으로 입력.
    """

    ticker: str = Field(
        min_length=1,
        max_length=20,
        description="거래소 티커 (예: 005930.KS 또는 AAPL)",
    )
    asset_class: AssetClass
    market: MarketType
    quantity: Decimal = Field(
        gt=Decimal("0"),
        description="보유 수량 (소수 단위 지원)",
    )
    average_cost: Decimal = Field(
        gt=Decimal("0"),
        description="평균 매수 단가 (currency_code 기준)",
    )
    currency_code: CurrencyCode
    execution_exchange_rate: Decimal = Field(
        gt=Decimal("0"),
        description="매수 당시 환율 (1 USD = N KRW). KRW 자산은 1.0",
    )

    @field_validator("ticker")
    @classmethod
    def uppercase_ticker(cls, v: str) -> str:
        return v.upper().strip()


class HoldingUpdate(BaseModel):
    """수량 또는 평균 단가 수정 (종목 자체는 변경 불가 — 삭제 후 재등록)"""

    quantity: Decimal | None = Field(default=None, gt=Decimal("0"))
    average_cost: Decimal | None = Field(default=None, gt=Decimal("0"))
    execution_exchange_rate: Decimal | None = Field(default=None, gt=Decimal("0"))


class HoldingResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    portfolio_id: uuid.UUID
    ticker: str
    asset_class: AssetClass
    market: MarketType
    quantity: Decimal
    average_cost: Decimal
    currency_code: CurrencyCode
    created_at: datetime
    updated_at: datetime
