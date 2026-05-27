"""
포트폴리오 실시간 가치 평가 서비스

수익률 분해 수식:
─────────────────────────────────────────────────────────────────────────
설정값:
  P0 = avg_cost                  (매수 평단가, 현지통화)
  P1 = current_price             (현재가, 현지통화)
  E0 = execution_exchange_rate   (매수 당시 환율, 1 USD = E0 KRW)
  E1 = current_exchange_rate     (현재 환율, 1 USD = E1 KRW)
  Q  = quantity                  (보유 수량)

원화 투자원금:
  cost_krw = P0 × Q × E0

현재 원화 평가액:
  value_krw = P1 × Q × E1

순수 주가 수익률 (현지통화 기준):
  price_return = (P1 - P0) / P0

환율 수익률:
  fx_return = (E1 - E0) / E0

복합 총 수익률 (정확한 곱셈 공식):
  total_return = (1 + price_return) × (1 + fx_return) - 1

포트폴리오 환율 기여 분리:
  price_contribution_krw = Σ [Q × (P1 - P0) × E0]  ← 환율 고정, 가격만 변동
  fx_contribution_krw    = Σ [Q × P1 × (E1 - E0)]  ← 가격 고정, 환율만 변동

KRW 자산: E0 = E1 = 1.0 → fx_return = 0, fx_contribution = 0
─────────────────────────────────────────────────────────────────────────
"""

import asyncio
from decimal import Decimal, DivisionByZero, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.market_data.base import AdapterError, PriceQuote
from app.adapters.market_data.exchange_rate_adapter import ExchangeRateAdapter
from app.adapters.market_data.factory import get_adapter_for_ticker
from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.models.user import User
from app.schemas.valuation import HoldingValuation, PortfolioValuation

_ZERO = Decimal("0")
_ONE = Decimal("1")
_HUNDRED = Decimal("100")


def _safe_div(numerator: Decimal, denominator: Decimal) -> Decimal:
    """0 나눗셈 방지."""
    try:
        if denominator == _ZERO:
            return _ZERO
        return numerator / denominator
    except (DivisionByZero, InvalidOperation):
        return _ZERO


def _calc_holding_valuation(
    holding: Holding,
    quote: PriceQuote | None,
    current_usd_krw: Decimal,
    error_msg: str | None = None,
) -> HoldingValuation:
    """
    단일 보유 종목의 실시간 평가값 계산.

    현재가를 가져오지 못한 경우(quote=None):
      - current_price = avg_cost (수익률 0 처리)
      - price_fetch_failed = True
    """
    avg_cost: Decimal = holding.average_cost
    quantity: Decimal = holding.quantity

    # ── 보유 종목 통화에 맞는 환율 설정 ────────────────────────────────
    if holding.currency_code.value == "KRW":
        current_exchange_rate = _ONE
    else:
        current_exchange_rate = current_usd_krw

    # 매수 당시 환율 (Holding 모델에 없으면 current로 대체 → fx_return=0)
    execution_exchange_rate: Decimal = getattr(
        holding, "execution_exchange_rate", current_exchange_rate
    )
    if execution_exchange_rate is None or execution_exchange_rate == _ZERO:
        execution_exchange_rate = current_exchange_rate

    price_fetch_failed = quote is None
    if quote is None:
        current_price = avg_cost      # 수익률 0
        data_source = "unavailable"
        name = None
    else:
        current_price = quote.current_price
        data_source = quote.source
        name = quote.name

    # ── 원화 환산 ────────────────────────────────────────────────────────
    cost_krw = avg_cost * quantity * execution_exchange_rate
    current_value_krw = current_price * quantity * current_exchange_rate
    unrealized_pnl_krw = current_value_krw - cost_krw

    # ── 수익률 분해 ──────────────────────────────────────────────────────
    # 주가 수익률 (현지통화 기준)
    price_return = _safe_div(current_price - avg_cost, avg_cost)

    # 환율 수익률
    fx_return = _safe_div(
        current_exchange_rate - execution_exchange_rate,
        execution_exchange_rate,
    )

    # 복합 총 수익률: (1 + price_r) × (1 + fx_r) - 1
    total_return = (_ONE + price_return) * (_ONE + fx_return) - _ONE

    return HoldingValuation(
        holding_id=holding.id,
        ticker=holding.ticker,
        name=name,
        asset_class=holding.asset_class,
        market=holding.market,
        currency_code=holding.currency_code,
        quantity=quantity,
        avg_cost=avg_cost,
        execution_exchange_rate=execution_exchange_rate,
        current_price=current_price,
        current_exchange_rate=current_exchange_rate,
        data_source=data_source,
        cost_krw=cost_krw.quantize(Decimal("0.01")),
        current_value_krw=current_value_krw.quantize(Decimal("0.01")),
        unrealized_pnl_krw=unrealized_pnl_krw.quantize(Decimal("0.01")),
        price_return_pct=(price_return * _HUNDRED).quantize(Decimal("0.0001")),
        fx_return_pct=(fx_return * _HUNDRED).quantize(Decimal("0.0001")),
        total_return_pct=(total_return * _HUNDRED).quantize(Decimal("0.0001")),
        price_fetch_failed=price_fetch_failed,
        error_message=error_msg,
    )


async def _fetch_quotes_parallel(
    holdings: list[Holding],
) -> dict[str, PriceQuote | None]:
    """
    어댑터 팩토리로 종목별 현재가를 병렬 조회.
    실패한 종목은 None 처리 (다른 종목 계산은 계속).
    """
    async def fetch_one(h: Holding) -> tuple[str, PriceQuote | None]:
        adapter = get_adapter_for_ticker(h.ticker)
        try:
            quote = await adapter.get_quote(h.ticker)
            return h.ticker, quote
        except (AdapterError, Exception):
            return h.ticker, None

    tasks = [fetch_one(h) for h in holdings]
    results = await asyncio.gather(*tasks, return_exceptions=False)
    return {ticker: quote for ticker, quote in results}


async def evaluate_portfolio(
    db: AsyncSession,
    portfolio: Portfolio,
    fx_adapter: ExchangeRateAdapter,
) -> PortfolioValuation:
    """
    포트폴리오 전체 실시간 가치 평가.

    1. 환율 조회 (USD/KRW)
    2. 보유 종목별 현재가 병렬 조회
    3. 종목별 원화 환산 + 수익률 분해
    4. 포트폴리오 집계 (투자원금 / 평가액 / 주가 기여 / 환율 기여)
    """
    # ── 1. 보유 종목 로드 ────────────────────────────────────────────────
    result = await db.execute(
        select(Holding).where(Holding.portfolio_id == portfolio.id)
    )
    holdings = list(result.scalars().all())

    # ── 2. 현재 환율 조회 ────────────────────────────────────────────────
    fx_rate = await fx_adapter.get_usd_krw()
    current_usd_krw = fx_rate.rate

    # ── 3. 현재가 병렬 조회 ──────────────────────────────────────────────
    quote_map = await _fetch_quotes_parallel(holdings)

    # ── 4. 종목별 평가 계산 ──────────────────────────────────────────────
    holding_valuations: list[HoldingValuation] = []
    for h in holdings:
        quote = quote_map.get(h.ticker)
        hv = _calc_holding_valuation(h, quote, current_usd_krw)
        holding_valuations.append(hv)

    # ── 5. 포트폴리오 집계 ───────────────────────────────────────────────
    total_cost_krw = sum((hv.cost_krw for hv in holding_valuations), _ZERO)
    total_value_krw = sum((hv.current_value_krw for hv in holding_valuations), _ZERO)
    total_unrealized_pnl_krw = total_value_krw - total_cost_krw
    total_return_pct = (
        _safe_div(total_unrealized_pnl_krw, total_cost_krw) * _HUNDRED
    ).quantize(Decimal("0.0001"))

    # ── 6. 주가 기여 / 환율 기여 분리 ────────────────────────────────────
    # price_contribution: 매수 환율 고정, 가격 변동분만 원화 환산
    # fx_contribution: 현재 가격 기준, 환율 변동분만 원화 환산
    price_contribution_krw = _ZERO
    fx_contribution_krw = _ZERO
    for h, hv in zip(holdings, holding_valuations):
        if hv.price_fetch_failed:
            continue
        # 주가 기여: Q × (P1 - P0) × E0
        price_contribution_krw += (
            hv.quantity
            * (hv.current_price - hv.avg_cost)
            * hv.execution_exchange_rate
        )
        # 환율 기여: Q × P1 × (E1 - E0)
        fx_contribution_krw += (
            hv.quantity
            * hv.current_price
            * (hv.current_exchange_rate - hv.execution_exchange_rate)
        )

    return PortfolioValuation(
        portfolio_id=portfolio.id,
        portfolio_name=portfolio.name,
        base_currency=portfolio.base_currency,
        holdings=holding_valuations,
        total_cost_krw=total_cost_krw.quantize(Decimal("0.01")),
        total_value_krw=total_value_krw.quantize(Decimal("0.01")),
        total_unrealized_pnl_krw=total_unrealized_pnl_krw.quantize(Decimal("0.01")),
        total_return_pct=total_return_pct,
        price_contribution_krw=price_contribution_krw.quantize(Decimal("0.01")),
        fx_contribution_krw=fx_contribution_krw.quantize(Decimal("0.01")),
        current_usd_krw_rate=current_usd_krw,
        rate_source=fx_rate.source,
    )
