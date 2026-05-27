"""
포트폴리오 실시간 가치 평가 응답 스키마

수익률 분해 원칙 (다중 통화 회계):
────────────────────────────────────────────────────────────────────
  매수 원화 투자원금   = execution_price × quantity × execution_exchange_rate
  현재 원화 평가액     = current_price × quantity × current_exchange_rate
  총 수익률           = (현재 원화 평가액 - 매수 원화 투자원금) / 매수 원화 투자원금

  주가 수익률 (현지통화 기준):
    price_return_pct = (current_price - avg_cost) / avg_cost

  환율 수익률 (환차익/환차손):
    fx_return_pct = (current_exchange_rate - execution_exchange_rate)
                   / execution_exchange_rate
    ※ KRW 자산은 execution_exchange_rate = 1.0 → fx_return_pct = 0.0

  산술 근사:
    total_return_pct ≈ price_return_pct + fx_return_pct
    (정확한 값은 (1 + price) × (1 + fx) - 1)
────────────────────────────────────────────────────────────────────
"""

import uuid
from decimal import Decimal

from pydantic import BaseModel, computed_field

from app.core.enums import AssetClass, CurrencyCode, MarketType


class HoldingValuation(BaseModel):
    """단일 보유 종목의 실시간 평가 결과."""

    model_config = {"from_attributes": True}

    holding_id: uuid.UUID
    ticker: str
    name: str | None
    asset_class: AssetClass
    market: MarketType
    currency_code: CurrencyCode

    # ── 보유 정보 (DB) ───────────────────────────────────────────────────
    quantity: Decimal
    avg_cost: Decimal                    # 평균 매수 단가 (현지통화)
    execution_exchange_rate: Decimal     # 매수 당시 환율

    # ── 실시간 시장 데이터 ────────────────────────────────────────────────
    current_price: Decimal               # 현재가 (현지통화)
    current_exchange_rate: Decimal       # 현재 환율 (KRW/USD 등)
    data_source: str

    # ── 원화 환산 금액 ────────────────────────────────────────────────────
    cost_krw: Decimal                    # 매수 원화 투자원금
    current_value_krw: Decimal          # 현재 원화 평가액
    unrealized_pnl_krw: Decimal         # 미실현 손익 (원화)

    # ── 수익률 분해 ───────────────────────────────────────────────────────
    price_return_pct: Decimal            # 순수 주가 변동 수익률 (%)
    fx_return_pct: Decimal               # 환율 변동 수익률 (%)
    total_return_pct: Decimal            # 복합 총 수익률 (%)

    # ── 오류 표시 ─────────────────────────────────────────────────────────
    price_fetch_failed: bool = False
    error_message: str | None = None


class PortfolioValuation(BaseModel):
    """포트폴리오 전체 실시간 가치 평가 결과."""

    portfolio_id: uuid.UUID
    portfolio_name: str
    base_currency: str

    # 종목별 상세
    holdings: list[HoldingValuation]

    # 포트폴리오 집계
    total_cost_krw: Decimal              # 전체 투자원금 (원화 환산)
    total_value_krw: Decimal             # 전체 현재 평가액 (원화 환산)
    total_unrealized_pnl_krw: Decimal    # 미실현 손익 합계
    total_return_pct: Decimal            # 전체 수익률 (%)

    # 통화별 분해
    price_contribution_krw: Decimal      # 주가 변동분 기여 (원화)
    fx_contribution_krw: Decimal         # 환율 변동분 기여 (원화)

    # 현재 환율 스냅샷
    current_usd_krw_rate: Decimal
    rate_source: str
