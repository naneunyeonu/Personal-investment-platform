"""
국내 주식 어댑터 — 한국투자증권 KIS Developers REST API

[구현 범위]
  ✅ OAuth 2.0 액세스 토큰 발급 (grant_type=client_credentials)
  ✅ 국내 주식 현재가 조회          (tr_id: FHKST01010100)
  ✅ 국내 주식 기본 시세 상세 조회  (tr_id: FHKST01010200)

[절대 구현 금지]
  ⛔ 주식 매수 주문  (tr_id: TTTC0802U)
  ⛔ 주식 매도 주문  (tr_id: TTTC0801U)
  ⛔ 모의투자 주문   (tr_id: VTTC*)
  → 이 플랫폼은 시세 조회 및 분석 서포트 전용

KIS API 공식 문서: https://apiportal.koreainvestment.com
"""

import asyncio
import time
from decimal import Decimal

import httpx

from app.adapters.market_data.base import AdapterError, MarketDataProvider, PriceQuote
from app.core.config import settings

_SOURCE = "kis"
_BASE_URL = "https://openapi.koreainvestment.com:9443"
_MOCK_URL = "https://openapivts.koreainvestment.com:29443"   # 모의투자 (미사용)

# KRX 종목 접미사 → KIS 처리 범위
_KRX_SUFFIXES = (".KS", ".KQ")


class _TokenCache:
    """액세스 토큰 인메모리 캐시 (만료 5분 전 자동 갱신)."""

    def __init__(self) -> None:
        self._token: str | None = None
        self._expires_at: float = 0.0

    def is_valid(self) -> bool:
        return self._token is not None and time.time() < self._expires_at - 300

    def set(self, token: str, expires_in: int) -> None:
        self._token = token
        self._expires_at = time.time() + expires_in

    @property
    def token(self) -> str | None:
        return self._token


_token_cache = _TokenCache()


class KISAdapter(MarketDataProvider):
    """
    한국투자증권 KIS Developers REST API 어댑터.

    - .KS (KOSPI) / .KQ (KOSDAQ) 접미사 종목 전용
    - 매매 기능 완전 배제 — 시세 조회만 제공
    - OAuth 토큰 자동 갱신 (인메모리 캐시)
    """

    def __init__(self) -> None:
        self._app_key = settings.KIS_APP_KEY
        self._app_secret = settings.KIS_APP_SECRET
        self._base_url = _BASE_URL

    # ── 공개 인터페이스 구현 ───────────────────────────────────────────────

    def supports(self, ticker: str) -> bool:
        """KRX 접미사(.KS / .KQ) 또는 6자리 숫자 종목코드 지원."""
        t = ticker.upper()
        if any(t.endswith(s) for s in _KRX_SUFFIXES):
            return True
        # 접미사 없는 6자리 숫자 코드 (예: 005930)
        return t.isdigit() and len(t) == 6

    async def get_quote(self, ticker: str) -> PriceQuote:
        stock_code = self._normalize_code(ticker)
        try:
            token = await self._ensure_token()
            data = await asyncio.to_thread(
                self._fetch_current_price, stock_code, token
            )
            return data
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterError(_SOURCE, f"Failed to fetch {ticker}: {exc}") from exc

    async def get_quotes(self, tickers: list[str]) -> dict[str, PriceQuote]:
        if not tickers:
            return {}
        results: dict[str, PriceQuote] = {}
        for ticker in tickers:
            try:
                results[ticker.upper()] = await self.get_quote(ticker)
            except AdapterError:
                continue
        return results

    # ── OAuth 토큰 관리 ───────────────────────────────────────────────────

    async def _ensure_token(self) -> str:
        if _token_cache.is_valid() and _token_cache.token:
            return _token_cache.token

        token, expires_in = await asyncio.to_thread(self._fetch_token)
        _token_cache.set(token, expires_in)
        return token

    def _fetch_token(self) -> tuple[str, int]:
        """
        KIS OAuth 2.0 액세스 토큰 발급.
        POST /oauth2/tokenP
        """
        if not self._app_key or not self._app_secret:
            raise AdapterError(
                _SOURCE,
                "KIS_APP_KEY / KIS_APP_SECRET 환경 변수가 설정되지 않았습니다.",
            )

        url = f"{self._base_url}/oauth2/tokenP"
        payload = {
            "grant_type": "client_credentials",
            "appkey": self._app_key,
            "appsecret": self._app_secret,
        }
        with httpx.Client(timeout=10) as client:
            resp = client.post(url, json=payload)

        if resp.status_code != 200:
            raise AdapterError(
                _SOURCE,
                f"Token issue failed: HTTP {resp.status_code} — {resp.text[:200]}",
            )

        body = resp.json()
        token = body.get("access_token")
        expires_in = int(body.get("expires_in", 86400))
        if not token:
            raise AdapterError(_SOURCE, "Empty access_token in response")
        return token, expires_in

    # ── 시세 조회 (매매 관련 API 절대 미사용) ─────────────────────────────

    def _fetch_current_price(self, stock_code: str, token: str) -> PriceQuote:
        """
        국내 주식 현재가 조회
        GET /uapi/domestic-stock/v1/quotations/inquire-price
        tr_id: FHKST01010100

        [사용하지 않는 tr_id]
        - TTTC0802U (매수), TTTC0801U (매도) — 주문 체결 API 절대 미사용
        """
        url = f"{self._base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": self._app_key,
            "appsecret": self._app_secret,
            "tr_id": "FHKST01010100",     # 국내 주식 현재가 시세
        }
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",   # J=주식, ETF=ETF, ELW=ELW
            "FID_INPUT_ISCD": stock_code,
        }

        with httpx.Client(timeout=10) as client:
            resp = client.get(url, headers=headers, params=params)

        if resp.status_code != 200:
            raise AdapterError(
                _SOURCE,
                f"Price fetch failed: HTTP {resp.status_code} — {resp.text[:200]}",
            )

        body = resp.json()
        if body.get("rt_cd") != "0":
            raise AdapterError(
                _SOURCE,
                f"KIS API error: {body.get('msg1', 'unknown')}",
            )

        output = body.get("output", {})
        current_price = Decimal(output.get("stck_prpr", "0"))          # 현재가
        previous_close = Decimal(output.get("stck_sdpr", "0"))         # 기준가(전일 종가)
        name = output.get("hts_kor_isnm", "")                          # 종목명

        day_change_pct: Decimal | None = None
        if previous_close and previous_close != 0:
            day_change_pct = Decimal(str(
                round(float((current_price - previous_close) / previous_close * 100), 4)
            ))

        return PriceQuote(
            ticker=stock_code,
            current_price=current_price,
            currency="KRW",
            previous_close=previous_close,
            day_change_pct=day_change_pct,
            name=name,
            source=_SOURCE,
        )

    def _fetch_detail(self, stock_code: str, token: str) -> dict:
        """
        국내 주식 기본 시세 상세 조회
        GET /uapi/domestic-stock/v1/quotations/inquire-daily-price
        tr_id: FHKST01010200

        시가 / 고가 / 저가 / 거래량 / 시가총액 등 세부 정보 반환.
        """
        url = f"{self._base_url}/uapi/domestic-stock/v1/quotations/inquire-daily-price"
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": self._app_key,
            "appsecret": self._app_secret,
            "tr_id": "FHKST01010200",     # 국내 주식 기본 시세 상세
        }
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": stock_code,
            "FID_PERIOD_DIV_CODE": "D",    # D=일, W=주, M=월
            "FID_ORG_ADJ_PRC": "0",
        }

        with httpx.Client(timeout=10) as client:
            resp = client.get(url, headers=headers, params=params)

        if resp.status_code != 200:
            raise AdapterError(
                _SOURCE,
                f"Detail fetch failed: HTTP {resp.status_code}",
            )

        return resp.json()

    # ── 헬퍼 ──────────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_code(ticker: str) -> str:
        """
        'AAPL' → 그대로 (supports()가 걸러냄)
        '005930.KS' → '005930'
        '000660.KQ' → '000660'
        '005930' → '005930'
        """
        t = ticker.upper()
        for suffix in _KRX_SUFFIXES:
            if t.endswith(suffix):
                return t[: -len(suffix)]
        return t
