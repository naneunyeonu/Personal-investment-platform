"""
글로벌 주식 어댑터 (yfinance)

- 미국 NYSE / NASDAQ / AMEX 및 기타 글로벌 거래소 종목 지원
- .KS / .KQ 접미사 ticker는 KIS 어댑터로 라우팅해야 함
- 매매 기능 없음 — 시세 조회 전용

yfinance 레이트 제한 대응:
- 단건 조회: yf.Ticker(ticker).fast_info
- 복수 조회: yf.download() + threads=True
"""

import asyncio
from decimal import Decimal
from functools import partial

import yfinance as yf

from app.adapters.market_data.base import AdapterError, MarketDataProvider, PriceQuote

_SOURCE = "yfinance"

# 한국 거래소 접미사 — KIS 어댑터가 처리해야 할 ticker 패턴
_KRX_SUFFIXES = (".KS", ".KQ", ".KN")


class YFinanceAdapter(MarketDataProvider):
    """
    yfinance 기반 글로벌 시세 어댑터.

    asyncio.to_thread()로 blocking I/O를 이벤트 루프 밖으로 오프로딩.
    """

    def supports(self, ticker: str) -> bool:
        """KRX 접미사 종목 제외, 나머지 전부 지원."""
        return not any(ticker.upper().endswith(s) for s in _KRX_SUFFIXES)

    # ── 단건 조회 ──────────────────────────────────────────────────────────
    async def get_quote(self, ticker: str) -> PriceQuote:
        try:
            quote = await asyncio.to_thread(self._fetch_single, ticker)
            return quote
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterError(_SOURCE, f"Failed to fetch {ticker}: {exc}") from exc

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
        yf.download()로 일괄 조회 → 종목별 PriceQuote 딕셔너리 반환.
        1개 실패해도 나머지는 계속 처리.
        """
        results: dict[str, PriceQuote] = {}
        # 개별 조회로 처리 (yf.download는 OHLCV만 반환)
        for ticker in tickers:
            try:
                results[ticker.upper()] = self._fetch_single(ticker)
            except AdapterError:
                # 개별 실패는 건너뜀 — 호출자가 누락 ticker 처리
                continue
        return results
