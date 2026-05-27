"""
시장 데이터 어댑터 팩토리 & FastAPI DI 공급자

선택 로직:
  ticker.endswith('.KS' | '.KQ') 또는 6자리 숫자  → KISAdapter
  그 외                                              → YFinanceAdapter

라우터 사용 예:
    @router.get("/quote/{ticker}")
    async def quote(
        ticker: str,
        provider: Annotated[MarketDataProvider, Depends(get_market_data_provider)],
        fx: Annotated[ExchangeRateAdapter, Depends(get_exchange_rate_adapter)],
    ): ...
"""

from typing import Annotated

from fastapi import Depends

from app.adapters.market_data.base import MarketDataProvider
from app.adapters.market_data.exchange_rate_adapter import ExchangeRateAdapter
from app.adapters.market_data.kis_adapter import KISAdapter
from app.adapters.market_data.yfinance_adapter import YFinanceAdapter

# 싱글톤 인스턴스 (앱 전체 공유, 상태 없음)
_yfinance_adapter = YFinanceAdapter()
_kis_adapter = KISAdapter()
_exchange_rate_adapter = ExchangeRateAdapter()

# 등록된 어댑터 목록 (우선순위 순)
_ADAPTERS: list[MarketDataProvider] = [
    _kis_adapter,        # KRX 종목 우선
    _yfinance_adapter,   # 글로벌 fallback
]


def get_adapter_for_ticker(ticker: str) -> MarketDataProvider:
    """
    ticker에 맞는 어댑터를 반환하는 팩토리 함수.
    등록된 어댑터 중 supports() == True인 첫 번째 어댑터 반환.
    """
    for adapter in _ADAPTERS:
        if adapter.supports(ticker):
            return adapter
    # 모두 실패하면 yfinance 기본 반환
    return _yfinance_adapter


# ── FastAPI Depends() 제공자 ──────────────────────────────────────────────


def get_yfinance_adapter() -> YFinanceAdapter:
    return _yfinance_adapter


def get_kis_adapter() -> KISAdapter:
    return _kis_adapter


def get_exchange_rate_adapter() -> ExchangeRateAdapter:
    return _exchange_rate_adapter


def get_market_data_provider(ticker: str = "") -> MarketDataProvider:
    """
    단일 ticker에 맞는 어댑터 반환.
    ticker가 비어 있으면 yfinance(글로벌 기본) 반환.
    """
    if not ticker:
        return _yfinance_adapter
    return get_adapter_for_ticker(ticker)
