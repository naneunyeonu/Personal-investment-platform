"""
E2E 안정화 테스트 — CORS · 재시도 · Graceful Degradation

검증 항목:
  1. CORS 설정 — 허용 오리진 목록 검증
  2. Retry 유틸리티 — async_retry / sync_retry 동작
  3. yfinance 어댑터 재시도 / AdapterError 즉시 전파
  4. KIS 어댑터 재시도 / 토큰 캐시 동작
  5. DART 어댑터 Graceful Degradation (API 키 없음 / 오류 시 빈 결과)
  6. SEC EDGAR 어댑터 Graceful Degradation
  7. 환율 어댑터 3단계 Fallback 체인 구조
"""

import asyncio
import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# ═════════════════════════════════════════════════════════════════════════════
# 1. CORS 설정 검증
# ═════════════════════════════════════════════════════════════════════════════

class TestCORSSettings:
    """
    ALLOWED_ORIGINS 기본값에 Vite 개발 서버(5173)가 포함되어 있어야 한다.
    allow_credentials=True 와 함께 사용하므로 "*" 와일드카드가 없어야 한다.
    """

    def test_vite_dev_port_included(self):
        """Vite 기본 포트 5173이 ALLOWED_ORIGINS에 포함되어야 한다."""
        from app.core.config import settings
        assert "http://localhost:5173" in settings.ALLOWED_ORIGINS

    def test_vite_preview_port_included(self):
        """Vite preview 포트 4173이 포함되어야 한다."""
        from app.core.config import settings
        assert "http://localhost:4173" in settings.ALLOWED_ORIGINS

    def test_127_0_0_1_variants_included(self):
        """127.0.0.1 변형이 포함되어야 한다."""
        from app.core.config import settings
        assert "http://127.0.0.1:5173" in settings.ALLOWED_ORIGINS

    def test_no_wildcard_origin(self):
        """allow_credentials=True와 병용 불가한 '*' 와일드카드가 없어야 한다."""
        from app.core.config import settings
        assert "*" not in settings.ALLOWED_ORIGINS

    def test_minimum_origins_count(self):
        """개발 편의를 위해 최소 4개 이상의 오리진이 설정되어야 한다."""
        from app.core.config import settings
        assert len(settings.ALLOWED_ORIGINS) >= 4

    def test_cors_middleware_registered(self):
        """FastAPI 앱에 CORSMiddleware가 등록되어 있어야 한다."""
        from fastapi.middleware.cors import CORSMiddleware
        from app.main import app
        middleware_types = [m.cls for m in app.user_middleware]
        assert CORSMiddleware in middleware_types

    @pytest.mark.asyncio
    async def test_health_endpoint_exposes_origins(self):
        """
        /health 엔드포인트 응답에 allowed_origins가 포함되어야 한다.
        운영 배포 후 CORS 설정 확인에 사용.
        """
        from httpx import AsyncClient, ASGITransport
        from app.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/health")
        data = resp.json()
        assert "allowed_origins" in data
        assert isinstance(data["allowed_origins"], list)


# ═════════════════════════════════════════════════════════════════════════════
# 2. Retry 유틸리티 검증
# ═════════════════════════════════════════════════════════════════════════════

class TestAsyncRetry:
    """async_retry() — 비동기 재시도 동작 검증."""

    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self):
        """첫 번째 시도에 성공하면 즉시 결과 반환."""
        from app.adapters.retry import async_retry

        async def succeed():
            return "ok"

        result = await async_retry(succeed, max_attempts=3)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_retry_on_connect_error(self):
        """ConnectError 발생 시 재시도하여 성공해야 한다."""
        from app.adapters.retry import async_retry

        call_count = 0

        async def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise httpx.ConnectError("연결 실패")
            return "recovered"

        with patch("app.adapters.retry.asyncio.sleep", new_callable=AsyncMock):
            result = await async_retry(fail_then_succeed, max_attempts=3, base_delay=0)
        assert result == "recovered"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retry_on_http_429(self):
        """HTTP 429 Rate Limit 응답 시 재시도해야 한다."""
        from app.adapters.retry import async_retry

        call_count = 0

        async def rate_limited():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                mock_resp = MagicMock()
                mock_resp.status_code = 429
                raise httpx.HTTPStatusError("429", request=MagicMock(), response=mock_resp)
            return "ok"

        with patch("app.adapters.retry.asyncio.sleep", new_callable=AsyncMock):
            result = await async_retry(rate_limited, max_attempts=3, base_delay=0)
        assert result == "ok"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_retry_on_http_503(self):
        """HTTP 503 서버 오류 응답 시 재시도해야 한다."""
        from app.adapters.retry import async_retry

        call_count = 0

        async def server_error():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                mock_resp = MagicMock()
                mock_resp.status_code = 503
                raise httpx.HTTPStatusError("503", request=MagicMock(), response=mock_resp)
            return "ok"

        with patch("app.adapters.retry.asyncio.sleep", new_callable=AsyncMock):
            result = await async_retry(server_error, max_attempts=3, base_delay=0)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_no_retry_on_http_400(self):
        """HTTP 400 클라이언트 오류는 재시도하지 않고 즉시 전파해야 한다."""
        from app.adapters.retry import async_retry

        call_count = 0

        async def bad_request():
            nonlocal call_count
            call_count += 1
            mock_resp = MagicMock()
            mock_resp.status_code = 400
            raise httpx.HTTPStatusError("400", request=MagicMock(), response=mock_resp)

        with pytest.raises(httpx.HTTPStatusError):
            await async_retry(bad_request, max_attempts=3, base_delay=0)
        assert call_count == 1  # 재시도 없이 1회

    @pytest.mark.asyncio
    async def test_raises_after_max_attempts(self):
        """max_attempts 초과 시 마지막 예외를 전파해야 한다."""
        from app.adapters.retry import async_retry

        call_count = 0

        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise httpx.ConnectError("항상 실패")

        with pytest.raises(httpx.ConnectError):
            with patch("app.adapters.retry.asyncio.sleep", new_callable=AsyncMock):
                await async_retry(always_fail, max_attempts=3, base_delay=0)
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_non_retryable_exception_propagates_immediately(self):
        """httpx 외 예외(ValueError 등)는 즉시 전파되어야 한다."""
        from app.adapters.retry import async_retry

        call_count = 0

        async def value_error():
            nonlocal call_count
            call_count += 1
            raise ValueError("데이터 오류")

        with pytest.raises(ValueError):
            await async_retry(value_error, max_attempts=3, base_delay=0)
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_exponential_backoff_delays(self):
        """지수 백오프 대기 시간이 올바르게 계산되어야 한다."""
        from app.adapters.retry import async_retry

        sleep_calls = []

        async def mock_sleep(delay: float):
            sleep_calls.append(delay)

        async def always_connect_error():
            raise httpx.ConnectError("fail")

        with patch("app.adapters.retry.asyncio.sleep", side_effect=mock_sleep):
            with pytest.raises(httpx.ConnectError):
                await async_retry(
                    always_connect_error,
                    max_attempts=3,
                    base_delay=1.0,
                    backoff_factor=2.0,
                )

        # attempt 1→2: 1.0s, attempt 2→3: 2.0s
        assert len(sleep_calls) == 2
        assert sleep_calls[0] == pytest.approx(1.0)
        assert sleep_calls[1] == pytest.approx(2.0)


class TestSyncRetry:
    """sync_retry() — 동기 재시도 동작 검증."""

    def test_success_first_try(self):
        from app.adapters.retry import sync_retry

        result = sync_retry(lambda: "ok", max_attempts=3)
        assert result == "ok"

    def test_retry_on_connect_error(self):
        from app.adapters.retry import sync_retry

        call_count = 0

        def fail_twice():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise httpx.ConnectError("연결 실패")
            return "recovered"

        with patch("app.adapters.retry.time.sleep"):
            result = sync_retry(fail_twice, max_attempts=3, base_delay=0)
        assert result == "recovered"
        assert call_count == 3

    def test_raises_after_max_attempts(self):
        from app.adapters.retry import sync_retry

        call_count = 0

        def always_fail():
            nonlocal call_count
            call_count += 1
            raise httpx.ConnectError("항상 실패")

        with pytest.raises(httpx.ConnectError):
            with patch("app.adapters.retry.time.sleep"):
                sync_retry(always_fail, max_attempts=3, base_delay=0)
        assert call_count == 3

    def test_no_retry_on_http_404(self):
        from app.adapters.retry import sync_retry

        call_count = 0

        def not_found():
            nonlocal call_count
            call_count += 1
            mock_resp = MagicMock()
            mock_resp.status_code = 404
            raise httpx.HTTPStatusError("404", request=MagicMock(), response=mock_resp)

        with pytest.raises(httpx.HTTPStatusError):
            sync_retry(not_found, max_attempts=3, base_delay=0)
        assert call_count == 1


# ═════════════════════════════════════════════════════════════════════════════
# 3. yfinance 어댑터 재시도 검증
# ═════════════════════════════════════════════════════════════════════════════

class TestYFinanceAdapterRetry:
    """yfinance 어댑터 재시도 및 AdapterError 즉시 전파 검증."""

    def test_adapter_error_not_retried(self):
        """
        AdapterError(No price data)는 재시도 없이 즉시 전파되어야 한다.
        데이터가 없는 종목을 3번 조회해도 의미 없음.
        """
        from app.adapters.market_data.yfinance_adapter import YFinanceAdapter
        from app.adapters.market_data.base import AdapterError

        adapter = YFinanceAdapter()

        call_count = 0

        def no_data_ticker(_ticker):
            nonlocal call_count
            call_count += 1
            raise AdapterError("yfinance", "No price data for INVALID")

        with patch.object(adapter, "_fetch_single", side_effect=no_data_ticker):
            with pytest.raises(AdapterError, match="No price data"):
                adapter._fetch_single_with_retry("INVALID")

        assert call_count == 1  # 재시도 없음

    def test_network_error_triggers_retry(self):
        """
        일반 Exception(네트워크 오류)은 최대 3회까지 재시도해야 한다.
        """
        from app.adapters.market_data.yfinance_adapter import YFinanceAdapter
        from app.adapters.market_data.base import AdapterError

        adapter = YFinanceAdapter()

        call_count = 0
        mock_quote = MagicMock()

        def fail_twice_then_succeed(_ticker):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("네트워크 오류")
            return mock_quote

        with patch.object(adapter, "_fetch_single", side_effect=fail_twice_then_succeed):
            with patch("app.adapters.market_data.yfinance_adapter.time.sleep"):
                result = adapter._fetch_single_with_retry("AAPL")

        assert result is mock_quote
        assert call_count == 3

    def test_persistent_failure_raises_adapter_error(self):
        """3회 모두 실패 시 AdapterError로 변환되어야 한다."""
        from app.adapters.market_data.yfinance_adapter import YFinanceAdapter
        from app.adapters.market_data.base import AdapterError

        adapter = YFinanceAdapter()

        def always_network_error(_ticker):
            raise ConnectionError("계속 실패")

        with patch.object(adapter, "_fetch_single", side_effect=always_network_error):
            with patch("app.adapters.market_data.yfinance_adapter.time.sleep"):
                with pytest.raises(AdapterError, match="Failed to fetch AAPL after 3 attempts"):
                    adapter._fetch_single_with_retry("AAPL")

    def test_batch_skips_failed_tickers(self):
        """배치 조회에서 개별 실패 종목은 건너뛰고 나머지 반환."""
        from app.adapters.market_data.yfinance_adapter import YFinanceAdapter
        from app.adapters.market_data.base import AdapterError, PriceQuote

        adapter = YFinanceAdapter()

        mock_aapl = MagicMock(spec=PriceQuote)

        def selective_fail(ticker):
            if ticker == "INVALID":
                raise AdapterError("yfinance", "No price data")
            return mock_aapl

        with patch.object(adapter, "_fetch_single_with_retry", side_effect=selective_fail):
            with patch("app.adapters.market_data.yfinance_adapter.time.sleep"):
                result = adapter._fetch_batch(["AAPL", "INVALID"])

        assert "AAPL" in result
        assert "INVALID" not in result


# ═════════════════════════════════════════════════════════════════════════════
# 4. KIS 어댑터 재시도 검증
# ═════════════════════════════════════════════════════════════════════════════

class TestKISAdapterRetry:
    """KIS 어댑터 재시도 및 토큰 캐시 동작 검증."""

    def test_token_fetch_retried_on_connect_error(self):
        """
        토큰 발급 시 ConnectError → sync_retry가 3회까지 재시도해야 한다.
        """
        from app.adapters.market_data.kis_adapter import KISAdapter
        from app.adapters.market_data.base import AdapterError

        adapter = KISAdapter()
        adapter._app_key = "test_key"
        adapter._app_secret = "test_secret"

        call_count = 0

        def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise httpx.ConnectError("KIS 서버 연결 실패")
            return ("mock_token", 86400)

        with patch.object(adapter, "_fetch_token", side_effect=fail_then_succeed):
            with patch("app.adapters.retry.time.sleep"):
                token, expires = adapter._fetch_token_with_retry()

        assert token == "mock_token"
        assert call_count == 3

    def test_token_fetch_raises_adapter_error_after_exhaustion(self):
        """3회 모두 실패 시 AdapterError가 발생해야 한다."""
        from app.adapters.market_data.kis_adapter import KISAdapter
        from app.adapters.market_data.base import AdapterError

        adapter = KISAdapter()

        def always_fail():
            raise httpx.ConnectError("계속 실패")

        with patch.object(adapter, "_fetch_token", side_effect=always_fail):
            with patch("app.adapters.retry.time.sleep"):
                with pytest.raises(AdapterError, match="Token fetch failed after retries"):
                    adapter._fetch_token_with_retry()

    def test_price_fetch_retried_on_timeout(self):
        """시세 조회 타임아웃 → sync_retry가 재시도해야 한다."""
        from app.adapters.market_data.kis_adapter import KISAdapter
        from app.adapters.market_data.base import PriceQuote

        adapter = KISAdapter()
        mock_quote = MagicMock(spec=PriceQuote)
        call_count = 0

        def timeout_once(stock_code, token):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.TimeoutException("타임아웃")
            return mock_quote

        with patch.object(adapter, "_fetch_current_price", side_effect=timeout_once):
            with patch("app.adapters.retry.time.sleep"):
                result = adapter._fetch_current_price_with_retry("005930", "token")

        assert result is mock_quote
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_token_cache_prevents_duplicate_fetch(self):
        """유효한 캐시 토큰이 있으면 토큰 재발급하지 않아야 한다."""
        from app.adapters.market_data.kis_adapter import KISAdapter, _token_cache

        # 캐시에 유효 토큰 설정
        _token_cache.set("cached_token", 86400)

        adapter = KISAdapter()

        fetch_called = False

        def should_not_be_called():
            nonlocal fetch_called
            fetch_called = True
            return ("new_token", 86400)

        with patch.object(adapter, "_fetch_token_with_retry", side_effect=should_not_be_called):
            token = await adapter._ensure_token()

        assert token == "cached_token"
        assert not fetch_called


# ═════════════════════════════════════════════════════════════════════════════
# 5. DART 어댑터 Graceful Degradation 검증
# ═════════════════════════════════════════════════════════════════════════════

class TestDARTAdapterGracefulDegradation:
    """DART API 키 없음·오류 시 앱 중단 없이 빈 결과 반환 검증."""

    @pytest.mark.asyncio
    async def test_empty_result_when_no_api_key(self):
        """DART_API_KEY 미설정 시 빈 결과 딕셔너리 반환 (예외 없음)."""
        from app.adapters.alternative_data.dart_adapter import DartAdapter

        adapter = DartAdapter()
        adapter._api_key = ""  # API 키 없음

        result = await adapter.get_financial_statements("005930")

        assert result["ticker"] == "005930"
        assert result["financials"] == {}
        assert "데이터 없음" in result["summary"] or "미설정" in result["summary"]
        assert "fetched_at" in result

    @pytest.mark.asyncio
    async def test_empty_result_on_network_error(self):
        """네트워크 오류 후 3회 재시도 모두 실패 시 graceful empty result 반환."""
        from app.adapters.alternative_data.dart_adapter import DartAdapter

        adapter = DartAdapter()
        adapter._api_key = "test_key"
        # corp_code 매핑을 미리 설정해 corpCode.xml 다운로드 우회
        adapter._corp_code_map = {"005930": "00126380"}

        with patch.object(
            adapter,
            "_fetch_financial_statements",
            side_effect=Exception("네트워크 오류"),
        ):
            result = await adapter.get_financial_statements("005930")

        assert result["financials"] == {}
        assert "API 오류" in result["summary"]

    @pytest.mark.asyncio
    async def test_invalid_ticker_returns_empty(self):
        """유효하지 않은 티커(US 주식 등) 입력 시 빈 결과 반환."""
        from app.adapters.alternative_data.dart_adapter import DartAdapter

        adapter = DartAdapter()
        adapter._api_key = "test_key"

        result = await adapter.get_financial_statements("AAPL")

        assert result["financials"] == {}
        assert "유효하지 않은" in result["summary"]

    @pytest.mark.asyncio
    async def test_corp_code_map_fallback_on_load_error(self):
        """
        corpCode.xml 다운로드 실패 시 corp_code_map이 비어 있어도
        get_financial_statements가 예외를 던지지 않아야 한다.
        """
        from app.adapters.alternative_data.dart_adapter import DartAdapter

        adapter = DartAdapter()
        adapter._api_key = "test_key"

        # _load_corp_code_map이 실패해도 _corp_code_map은 빈 dict
        with patch.object(adapter, "_load_corp_code_map", side_effect=Exception("ZIP 로드 실패")):
            result = await adapter.get_financial_statements("005930")

        # corp_code 조회 실패 → empty result
        assert result["financials"] == {}


# ═════════════════════════════════════════════════════════════════════════════
# 6. SEC EDGAR 어댑터 Graceful Degradation 검증
# ═════════════════════════════════════════════════════════════════════════════

class TestSECEdgarAdapterGracefulDegradation:
    """SEC API 오류 시 앱 중단 없이 빈 결과 반환 검증."""

    @pytest.mark.asyncio
    async def test_empty_result_on_network_failure(self):
        """모든 재시도 소진 후에도 empty_result를 반환해야 한다."""
        from app.adapters.alternative_data.sec_edgar_adapter import SecEdgarAdapter

        adapter = SecEdgarAdapter()
        adapter._use_secapi = False  # EDGAR 무료 경로 사용

        with patch.object(
            adapter,
            "_fetch_via_edgar_efts",
            side_effect=Exception("네트워크 오류"),
        ):
            result = await adapter.get_insider_transactions("AAPL")

        assert result["ticker"] == "AAPL"
        assert result["signal"] == "NO_DATA"
        assert result["filings"] == []
        assert "조회 불가" in result["summary"]

    @pytest.mark.asyncio
    async def test_empty_result_when_secapi_fails(self):
        """sec-api.io 경로 실패 시에도 graceful empty result."""
        from app.adapters.alternative_data.sec_edgar_adapter import SecEdgarAdapter

        adapter = SecEdgarAdapter()
        adapter._api_key = "test_key"
        adapter._use_secapi = True

        with patch.object(
            adapter,
            "_fetch_via_secapi",
            side_effect=httpx.ConnectError("연결 실패"),
        ):
            result = await adapter.get_insider_transactions("TSLA")

        assert result["signal"] == "NO_DATA"
        assert result["filings"] == []

    @pytest.mark.asyncio
    async def test_result_structure_always_valid(self):
        """
        성공/실패 무관하게 결과 딕셔너리가 항상 필수 필드를 포함해야 한다.
        """
        from app.adapters.alternative_data.sec_edgar_adapter import SecEdgarAdapter

        adapter = SecEdgarAdapter()
        adapter._use_secapi = False

        with patch.object(
            adapter,
            "_fetch_via_edgar_efts",
            side_effect=Exception("오류"),
        ):
            result = await adapter.get_insider_transactions("MSFT")

        required_fields = {"ticker", "signal", "filings", "summary", "fetched_at"}
        assert required_fields.issubset(result.keys())

    @pytest.mark.asyncio
    async def test_retry_called_on_connect_error(self):
        """
        async_retry가 ConnectError 시 재시도하여 성공 경로에 도달해야 한다.
        """
        from app.adapters.alternative_data.sec_edgar_adapter import SecEdgarAdapter

        adapter = SecEdgarAdapter()
        adapter._use_secapi = False

        call_count = 0

        async def fail_then_return(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise httpx.ConnectError("일시 오류")
            return {"hits": {"hits": []}}

        with patch.object(adapter, "_fetch_efts_once", side_effect=fail_then_return):
            with patch("app.adapters.retry.asyncio.sleep", new_callable=AsyncMock):
                result = await adapter.get_insider_transactions("AAPL")

        assert call_count == 3
        assert result["signal"] == "NO_DATA"  # 빈 hits → NO_DATA


# ═════════════════════════════════════════════════════════════════════════════
# 7. 환율 어댑터 Fallback 체인 검증
# ═════════════════════════════════════════════════════════════════════════════

class TestExchangeRateAdapterFallback:
    """3단계 Fallback(yfinance → exchangerate-api → 캐시) 체인 검증."""

    @pytest.mark.asyncio
    async def test_uses_cache_when_valid(self):
        """유효한 캐시가 있으면 외부 API 호출 없이 캐시값 반환."""
        from app.adapters.market_data import exchange_rate_adapter as era
        from app.adapters.market_data.exchange_rate_adapter import ExchangeRateAdapter, _RateCache

        # 캐시에 유효값 삽입
        era._rate_cache["USD/KRW"] = _RateCache(
            rate=Decimal("1350.00"),
            expires_at=time.time() + 300,
        )

        adapter = ExchangeRateAdapter()
        result = await adapter.get_usd_krw()

        assert result.rate == Decimal("1350.00")
        assert result.source == "cache"

    @pytest.mark.asyncio
    async def test_fallback_to_exchangerate_api_when_yfinance_fails(self):
        """yfinance 실패 시 exchangerate-api.com으로 fallback."""
        from app.adapters.market_data import exchange_rate_adapter as era
        from app.adapters.market_data.exchange_rate_adapter import ExchangeRateAdapter

        # 캐시 초기화
        era._rate_cache.clear()

        async def mock_fetch_fallback() -> Decimal:
            return Decimal("1380.00")

        adapter = ExchangeRateAdapter()
        with patch.object(adapter, "_fetch_yfinance", side_effect=Exception("yfinance 실패")):
            with patch.object(
                adapter, "_fetch_exchangerate_api", new_callable=AsyncMock,
                return_value=Decimal("1380.00"),
            ):
                result = await adapter.get_usd_krw()

        assert result.rate == Decimal("1380.00")

    @pytest.mark.asyncio
    async def test_last_cache_fallback_when_all_sources_fail(self):
        """yfinance + exchangerate-api 모두 실패 시 마지막 캐시값 사용."""
        from app.adapters.market_data import exchange_rate_adapter as era
        from app.adapters.market_data.exchange_rate_adapter import ExchangeRateAdapter, _RateCache

        # 만료된 캐시 설정 (is_valid() = False)
        era._rate_cache["USD/KRW"] = _RateCache(
            rate=Decimal("1320.00"),
            expires_at=time.time() - 10,   # 이미 만료
        )

        adapter = ExchangeRateAdapter()
        with patch.object(adapter, "_fetch_yfinance", side_effect=Exception("실패")):
            with patch.object(
                adapter, "_fetch_exchangerate_api",
                new_callable=AsyncMock,
                side_effect=Exception("실패"),
            ):
                # 만료 캐시라도 마지막 값 반환 (AdapterError 발생하지 않음)
                result = await adapter.get_usd_krw()

        assert result.rate == Decimal("1320.00")

    @pytest.mark.asyncio
    async def test_adapter_error_when_all_fail_no_cache(self):
        """캐시도 없고 모든 소스 실패 시 AdapterError 발생."""
        from app.adapters.market_data import exchange_rate_adapter as era
        from app.adapters.market_data.exchange_rate_adapter import ExchangeRateAdapter
        from app.adapters.market_data.base import AdapterError

        era._rate_cache.clear()

        adapter = ExchangeRateAdapter()
        with patch.object(adapter, "_fetch_yfinance", side_effect=Exception("실패")):
            with patch.object(
                adapter, "_fetch_exchangerate_api",
                new_callable=AsyncMock,
                side_effect=Exception("실패"),
            ):
                with pytest.raises(AdapterError, match="All exchange rate sources failed"):
                    await adapter.get_usd_krw()


# ═════════════════════════════════════════════════════════════════════════════
# 8. JWT 인터셉터 로직 검증 (프론트엔드 동작 명세)
# ═════════════════════════════════════════════════════════════════════════════

class TestJWTInterceptorBehaviorSpec:
    """
    프론트엔드 Axios 인터셉터 동작 명세.
    실제 브라우저 환경이 아니므로 Python 레벨에서 로직을 문서화.
    """

    def test_refresh_endpoint_path_constant(self):
        """
        JWT 재발급 엔드포인트가 POST /api/v1/auth/refresh 임을 백엔드 라우터에서 확인.
        프론트엔드 client.ts의 URL('/api/v1/auth/refresh')과 일치해야 한다.
        """
        from app.api.v1.router import api_v1_router
        paths = [r.path for r in api_v1_router.routes]
        # /auth/refresh 경로가 존재해야 한다
        assert any("refresh" in p for p in paths)

    def test_access_token_short_expiry(self):
        """
        Access token 만료 시간(60분)이 적절하게 설정되어 있어야 한다.
        너무 길면 보안 위험, 너무 짧으면 UX 저하.
        """
        from app.core.config import settings
        assert 15 <= settings.ACCESS_TOKEN_EXPIRE_MINUTES <= 120

    def test_refresh_token_reasonable_expiry(self):
        """Refresh token 만료 기간이 1일 이상 30일 이하여야 한다."""
        from app.core.config import settings
        assert 1 <= settings.REFRESH_TOKEN_EXPIRE_DAYS <= 30

    def test_auth_router_has_refresh_endpoint(self):
        """
        FastAPI auth 라우터에 POST /auth/refresh 엔드포인트가 존재해야 한다.
        (프론트엔드 인터셉터의 POST '/api/v1/auth/refresh' 와 매핑)
        """
        from app.api.v1.routers.auth import router as auth_router
        route_methods = {
            route.path: {m for m in route.methods or []}
            for route in auth_router.routes
            if hasattr(route, "methods")
        }
        refresh_path = "/auth/refresh"
        assert refresh_path in route_methods
        assert "POST" in route_methods[refresh_path]
