"""
포트폴리오 실시간 가치 평가 라우터

GET /api/v1/portfolios/{id}/valuation
  → 실시간 현재가 + 환율 반영 평가액
  → 주가 수익률 / 환차익 분리 응답

GET /api/v1/market/quote/{ticker}
  → 단일 종목 현재가 조회 (어댑터 팩토리 자동 선택)

GET /api/v1/market/fx/usd-krw
  → USD/KRW 현재 환율 조회

핵심 제약: 시세 조회 및 분석 전용. 매수/매도 기능 없음.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.market_data.base import AdapterError, PriceQuote
from app.adapters.market_data.exchange_rate_adapter import ExchangeRateAdapter
from app.adapters.market_data.factory import (
    get_adapter_for_ticker,
    get_exchange_rate_adapter,
)
from app.auth.dependencies import get_current_active_user
from app.db.session import get_db
from app.models.portfolio import Portfolio
from app.models.user import User
from app.schemas.valuation import PortfolioValuation
from app.services.portfolio_service import _get_portfolio_or_404
from app.services.valuation_service import evaluate_portfolio

router = APIRouter(tags=["Market Data & Valuation"])


# ── 포트폴리오 전체 실시간 평가 ─────────────────────────────────────────────

@router.get(
    "/portfolios/{portfolio_id}/valuation",
    response_model=PortfolioValuation,
    summary="포트폴리오 실시간 가치 평가",
    description=(
        "보유 종목의 실시간 현재가와 환율을 반영하여 포트폴리오 평가액을 계산합니다. "
        "**수익률 분해:** "
        "price_return_pct(순수 주가 변동), fx_return_pct(환차익/환차손), "
        "total_return_pct = (1+주가) × (1+환율) - 1. "
        "price_contribution_krw / fx_contribution_krw 로 원화 기여 분리."
    ),
)
async def get_portfolio_valuation(
    portfolio_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    fx_adapter: Annotated[ExchangeRateAdapter, Depends(get_exchange_rate_adapter)],
) -> PortfolioValuation:
    portfolio = await _get_portfolio_or_404(db, portfolio_id, current_user)
    return await evaluate_portfolio(db, portfolio, fx_adapter)


# ── 단일 종목 현재가 조회 ────────────────────────────────────────────────────

@router.get(
    "/market/quote/{ticker}",
    response_model=dict,
    summary="단일 종목 현재가 조회",
    description="ticker에 따라 자동으로 어댑터 선택: .KS/.KQ/6자리 숫자 → KIS, 그 외 → yfinance",
)
async def get_market_quote(
    ticker: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict:
    adapter = get_adapter_for_ticker(ticker.upper())
    try:
        quote = await adapter.get_quote(ticker.upper())
    except AdapterError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )
    return {
        "ticker": quote.ticker,
        "name": quote.name,
        "current_price": float(quote.current_price),
        "currency": quote.currency,
        "previous_close": float(quote.previous_close) if quote.previous_close else None,
        "day_change_pct": float(quote.day_change_pct) if quote.day_change_pct else None,
        "source": quote.source,
    }


# ── USD/KRW 환율 조회 ────────────────────────────────────────────────────────

@router.get(
    "/market/fx/usd-krw",
    response_model=dict,
    summary="USD/KRW 현재 환율 조회",
)
async def get_usd_krw(
    current_user: Annotated[User, Depends(get_current_active_user)],
    fx_adapter: Annotated[ExchangeRateAdapter, Depends(get_exchange_rate_adapter)],
) -> dict:
    try:
        rate = await fx_adapter.get_usd_krw()
    except AdapterError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )
    return {
        "base": rate.base,
        "quote": rate.quote,
        "rate": float(rate.rate),
        "source": rate.source,
    }
