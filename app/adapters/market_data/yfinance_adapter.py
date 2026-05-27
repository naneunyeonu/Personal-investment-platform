"""
글로벌 주식 어댑터 (yfinance)

- 미국 NYSE / NASDAQ / AMEX 및 기타 글로벌 거래소 종목 지원
- .KS / .KQ 접미사 ticker는 KIS 어댑터로 라우팅해야 함
- 매매 기능 없음 — 시세 조회 전용

재시도 전략:
- 네트워크 일시 오류(ConnectionError, Timeout 등) → 최대 3회 지수 백오프
- yfinance 내부는 requests 라이브러리 사용 → requests.exceptions.* 포착
- "No price data" (AdapterError) → 재시도 없이 즉시 전파 (데이터 없음은 확정적)
- 배치 조회: 개별 종목 실패는 건너뜀 (다른 종목 계속 처리)
"""

import asyncio
import logging
import time
from decimal import Decimal

import yfinance as yf

from app.adapters.market_data.base import AdapterError, MarketDataProvider, PriceQuote

logger = logging.getLogger(__name__)

_SOURCE = "yfinance"

# 한국 거래소 접미사 — KIS 어댑터가 처리해야 할 ticker 패턴
_KRX_SUFFIXES = (".KS", ".KQ", ".KN")

# 재시도 설정
_MAX_RETRY     = 3
_BASE_DELAY    = 1.0   # 첫 재시도 대기 (초)
_BACKOFF       = 2.0   # 지수 배수 → 1s, 2s 대기


class YFinanceAdapter(MarketDataProvider):
    """
    yfinance 기반 글로벌 시세 어댑터.

    asyncio.to_thread()로 blocking I/O를 이벤트 루프 밖으로 오프로딩.
    네트워크 일시 오류에 지수 백오프 재시도 적용.
    """

    def supports(self, ticker: str) -> bool:
        """KRX 접미사 종목 제외, 나머지 전부 지원."""
        return not any(ticker.upper().endswith(s) for s in _KRX_SUFFIXES)

    # ── 단건 조회 ──────────────────────────────────────────────────────────
    async def get_quote(self, ticker: str) -> PriceQuote:
        try:
            quote = await asyncio.to_thread(self._fetch_single_with_retry, ticker)
            return quote
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterError(_SOURCE, f"Failed to fetch {ticker}: {exc}") from exc

    def _fetch_single_with_retry(self, ticker: str) -> PriceQuote:
        """
        단건 조회 + 재시도 래퍼.
        네트워크 오류 시 최대 _MAX_RETRY 회 지수 백오프 재시도.
        """
        last_exc: Exception | None = None

        for attempt in range(1, _MAX_RETRY + 1):
            try:
                return self._fetch_single(ticker)
            except AdapterError:
                # "No price data" 등 확정적 실패 → 재시도 불필요
                raise
            except Exception as exc:
                last_exc = exc
                if attempt < _MAX_RETRY:
                    delay = _BASE_DELAY * (_BACKOFF ** (attempt - 1))
                    logger.debug(
                        "yfinance 재시도 %d/%d — %.1fs 대기 | ticker=%s error=%s",
                        attempt, _MAX_RETRY, delay, ticker, exc,
                    )
                    time.sleep(delay)

        raise AdapterError(
            _SOURCE,
            f"Failed to fetch {ticker} after {_MAX_RETRY} attempts: {last_exc}",
        ) from last_exc

    def _fetch_single(self, ticker: str) -> PriceQuote:
        t = yf.Ticker(ticker)
        info = t.fast_info  # 경량 캐시 (네트워크 1회 요청)

        current_price = getattr(info, "last_price", None)
        if current_price is None:
            # fast_info 실패 시 full info fallback
            full = t.info
            current_price = full.get("currentPrice") or full.get("regularMarketPrice")
        if current_price is None:
            raise AdapterError(_SOURCE, f"No price data for {ticker}")

        previous_close = getattr(info, "previous_close", None)
        day_change_pct: Decimal | None = None
        if current_price and previous_close and previous_close != 0:
            day_change_pct = Decimal(str(
                round((current_price - previous_close) / previous_close * 100, 4)
            ))

        currency = getattr(info, "currency", "USD") or "USD"

        return PriceQuote(
            ticker=ticker.upper(),
            current_price=Decimal(str(current_price)),
            currency=currency.upper(),
            previous_close=Decimal(str(previous_close)) if previous_close else None,
            day_change_pct=day_change_pct,
            market_cap=Decimal(str(info.market_cap)) if getattr(info, "market_cap", None) else None,
            name=getattr(info, "short_name", None),
            source=_SOURCE,
        )

    # ── 복수 일괄 조회 ──────────────────────────────────────────────────────
    async def get_quotes(self, tickers: list[str]) -> dict[str, PriceQuote]:
        if not tickers:
            return {}
        try:
            results = await asyncio.to_thread(self._fetch_batch, tickers)
            return results
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterError(_SOURCE, f"Batch fetch failed: {exc}") from exc

    def _fetch_batch(self, tickers: list[str]) -> dict[str, PriceQuote]:
        """
        종목별 개별 조회 — 1개 실패해도 나머지는 계속 처리.
        각 종목에 재시도 포함 (_fetch_single_with_retry).
        """
        results: dict[str, PriceQuote] = {}
        for ticker in tickers:
            try:
                results[ticker.upper()] = self._fetch_single_with_retry(ticker)
            except (AdapterError, Exception):
                # 개별 실패는 건너뜀 — 호출자가 누락 ticker 처리
                logger.debug("yfinance 배치 조회 실패 (건너뜀): %s", ticker)
                continue
        return results
