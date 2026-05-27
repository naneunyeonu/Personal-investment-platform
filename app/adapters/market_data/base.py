"""
시장 데이터 어댑터 추상 인터페이스

모든 벤더별 구현체(yfinance, KIS, 환율)는 이 ABC를 상속해야 함.
라우터·서비스는 이 인터페이스에만 의존 → 벤더 교체 시 구현체만 변경.

데이터 흐름:
  Router/Service
      ↓ Depends(get_market_data_provider)  ← 팩토리 DI
  MarketDataProvider (ABC)
      ↑ implements
  YFinanceAdapter | KISAdapter | ...
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class PriceQuote:
    """
    단일 종목 현재가 스냅샷.
    currency는 해당 거래소 원래 통화 (KRW / USD 등 ISO 4217).
    """

    ticker: str
    current_price: Decimal
    currency: str                    # ISO 4217
    previous_close: Decimal | None = None
    day_change_pct: Decimal | None = None   # 전일 대비 등락률 (%)
    market_cap: Decimal | None = None
    name: str | None = None
    source: str = "unknown"          # 데이터 출처 식별자 ("yfinance" | "kis" | …)


@dataclass
class ExchangeRate:
    """원화 기준 환율 스냅샷."""

    base: str        # 기준 통화 (예: "USD")
    quote: str       # 견적 통화 (항상 "KRW")
    rate: Decimal    # 1 base = rate KRW
    source: str = "unknown"


class MarketDataProvider(ABC):
    """
    시장 데이터 공급자 추상 인터페이스.

    구현체 작성 규칙:
    - get_quote() 내부에서 네트워크 오류 발생 시 httpx.HTTPError 또는
      자체 AdapterError를 raise 하여 라우터에서 503으로 처리할 수 있도록 함.
    - 매매(주문 체결) 관련 메서드는 이 인터페이스에 절대 추가하지 않음.
    """

    @abstractmethod
    async def get_quote(self, ticker: str) -> PriceQuote:
        """종목 현재가 조회."""
        ...

    @abstractmethod
    async def get_quotes(self, tickers: list[str]) -> dict[str, PriceQuote]:
        """복수 종목 현재가 일괄 조회. key = ticker."""
        ...

    @abstractmethod
    def supports(self, ticker: str) -> bool:
        """이 어댑터가 해당 ticker를 처리할 수 있는지 여부."""
        ...


class AdapterError(Exception):
    """외부 데이터 소스 오류를 래핑하는 공통 예외."""

    def __init__(self, source: str, message: str) -> None:
        self.source = source
        super().__init__(f"[{source}] {message}")
