"""
환율 어댑터 — USD/KRW 실시간 환율 조회

전략:
1. 1차: yfinance에서 KRW=X (USD/KRW 직접 조회) → 가장 정확, 무료
2. 2차 fallback: exchangerate-api.com 공개 엔드포인트 (API 키 불필요)
3. 3차 fallback: 마지막 성공 캐시값 사용

캐시: 5분 TTL (환율은 초 단위 갱신 불필요)
"""

import asyncio
import time
from dataclasses import dataclass
from decimal import Decimal

import httpx
import yfinance as yf

from app.adapters.market_data.base import AdapterError, ExchangeRate

_SOURCE = "exchange_rate"
_CACHE_TTL_SEC = 300  # 5분


@dataclass
class _RateCache:
    rate: Decimal
    expires_at: float

    def is_valid(self) -> bool:
        return time.time() < self.expires_at


_rate_cache: dict[str, _RateCache] = {}   # key: "USD/KRW"


class ExchangeRateAdapter:
    """
    실시간 환율 조회 어댑터.
    현재 지원: USD → KRW (확장 시 base 파라미터 활용)
    """

    async def get_usd_krw(self) -> ExchangeRate:
        """USD/KRW 실시간 환율. 5분 캐시 적용."""
        cache_key = "USD/KRW"
        cached = _rate_cache.get(cache_key)
        if cached and cached.is_valid():
            return ExchangeRate(
                base="USD", quote="KRW", rate=cached.rate, source="cache"
            )

        rate = await self._fetch_with_fallback()
        _rate_cache[cache_key] = _RateCache(
            rate=rate, expires_at=time.time() + _CACHE_TTL_SEC
        )
        return ExchangeRate(base="USD", quote="KRW", rate=rate, source=_SOURCE)

    async def get_rate(self, base: str, quote: str = "KRW") -> ExchangeRate:
        """범용 환율 조회 (현재 USD/KRW만 구현)."""
        if base.upper() == "USD" and quote.upper() == "KRW":
            return await self.get_usd_krw()
        if base.upper() == "KRW":
            return ExchangeRate(base="KRW", quote="KRW", rate=Decimal("1"), source="identity")
        raise AdapterError(_SOURCE, f"Unsupported pair: {base}/{quote}")

    # ── 내부 조회 로직 ────────────────────────────────────────────────────

    async def _fetch_with_fallback(self) -> Decimal:
        """1차 yfinance → 2차 exchangerate-api fallback"""
        try:
            rate = await asyncio.to_thread(self._fetch_yfinance)
            if rate and rate > 0:
                return rate
        except Exception:
            pass

        try:
            rate = await self._fetch_exchangerate_api()
            if rate and rate > 0:
                return rate
        except Exception:
            pass

        # 캐시 만료됐지만 마지막 값이라도 반환
        cached = _rate_cache.get("USD/KRW")
        if cached:
            return cached.rate

        raise AdapterError(_SOURCE, "All exchange rate sources failed")

    @staticmethod
    def _fetch_yfinance() -> Decimal:
        """yfinance KRW=X 티커로 USD/KRW 조회"""
        ticker = yf.Ticker("KRW=X")
        info = ticker.fast_info
        price = getattr(info, "last_price", None)
        if price is None:
            raise AdapterError(_SOURCE, "yfinance KRW=X returned no price")
        return Decimal(str(round(price, 2)))

    @staticmethod
    async def _fetch_exchangerate_api() -> Decimal:
        """
        exchangerate-api.com 공개 API (무료, API 키 불필요).
        https://open.er-api.com/v6/latest/USD
        """
        url = "https://open.er-api.com/v6/latest/USD"
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(url)

        if resp.status_code != 200:
            raise AdapterError(_SOURCE, f"exchangerate-api HTTP {resp.status_code}")

        data = resp.json()
        krw_rate = data.get("rates", {}).get("KRW")
        if not krw_rate:
            raise AdapterError(_SOURCE, "KRW rate not found in response")
        return Decimal(str(round(float(krw_rate), 2)))
