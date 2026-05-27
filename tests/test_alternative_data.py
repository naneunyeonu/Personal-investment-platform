"""
대안 데이터(Alternative Data) 파이프라인 테스트

architecture_plan.md §6 구현 검증:
  - SEC EDGAR Form 4 내부자 거래 파싱 및 시그널 분류
  - Open DART 재무공시 파싱 및 비율 계산
  - Redis 캐시 set/get/track 동작
  - 프롬프트 주입 (_format_alternative_data)
  - Celery 태스크 헬퍼 (_fetch_alternative_data_safe)
"""

import json
from decimal import Decimal
from unittest.mock import MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# SEC EDGAR 어댑터 파싱 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestSecSignalClassification:
    """_classify_signal() — 내부자 거래 시그널 분류 로직."""

    def _make_filing(self, tx_type: str, value_usd: float, is_deriv: bool = False) -> dict:
        return {
            "filed_at": "2025-01-15",
            "reporter_name": "John Doe",
            "reporter_title": "CEO",
            "transaction_type": tx_type,
            "shares_traded": 1000.0,
            "price_per_share": value_usd / 1000,
            "total_value_usd": value_usd,
            "is_derivative": is_deriv,
            "shares_owned_after": 50000.0,
        }

    def test_no_data_when_empty(self):
        from app.adapters.alternative_data.sec_edgar_adapter import _classify_signal
        assert _classify_signal([]) == "NO_DATA"

    def test_strong_sell_above_5m(self):
        from app.adapters.alternative_data.sec_edgar_adapter import _classify_signal
        filings = [self._make_filing("S", 3_000_000), self._make_filing("S", 2_500_000)]
        assert _classify_signal(filings) == "STRONG_SELL"

    def test_moderate_sell_1m_to_5m(self):
        from app.adapters.alternative_data.sec_edgar_adapter import _classify_signal
        filings = [self._make_filing("S", 2_000_000)]
        assert _classify_signal(filings) == "MODERATE_SELL"

    def test_neutral_under_1m_sell(self):
        from app.adapters.alternative_data.sec_edgar_adapter import _classify_signal
        filings = [self._make_filing("S", 500_000)]
        assert _classify_signal(filings) == "NEUTRAL"

    def test_buy_signal_when_net_positive(self):
        from app.adapters.alternative_data.sec_edgar_adapter import _classify_signal
        filings = [self._make_filing("P", 1_500_000)]
        assert _classify_signal(filings) == "BUY"

    def test_buy_wins_over_small_sell(self):
        from app.adapters.alternative_data.sec_edgar_adapter import _classify_signal
        filings = [
            self._make_filing("P", 3_000_000),
            self._make_filing("S", 500_000),
        ]
        assert _classify_signal(filings) == "BUY"

    def test_derivatives_excluded_from_signal(self):
        """파생상품(옵션 행사) 트랜잭션은 시그널 계산에서 제외해야 함."""
        from app.adapters.alternative_data.sec_edgar_adapter import _classify_signal
        # 파생상품만 있는 경우 → NEUTRAL (거래 있지만 실질 signal 없음)
        filings = [self._make_filing("S", 10_000_000, is_deriv=True)]
        assert _classify_signal(filings) == "NEUTRAL"

    def test_neutral_only_derivatives_no_real_trades(self):
        """파생상품만 있으면 real_trades가 빈 리스트 → NEUTRAL."""
        from app.adapters.alternative_data.sec_edgar_adapter import _classify_signal
        filings = [
            self._make_filing("S", 6_000_000, is_deriv=True),
            self._make_filing("A", 0.0, is_deriv=True),
        ]
        assert _classify_signal(filings) == "NEUTRAL"


class TestSecSummaryBuilding:
    """_build_sec_summary() — LLM 프롬프트 주입용 텍스트."""

    def _make_sell_filing(self, value: float) -> dict:
        return {
            "filed_at": "2025-02-01",
            "reporter_name": "Jane Smith",
            "reporter_title": "CFO",
            "transaction_type": "S",
            "shares_traded": 10000.0,
            "price_per_share": value / 10000,
            "total_value_usd": value,
            "is_derivative": False,
            "shares_owned_after": 200000.0,
        }

    def test_summary_contains_ticker(self):
        from app.adapters.alternative_data.sec_edgar_adapter import _build_sec_summary
        summary = _build_sec_summary("AAPL", [], "NO_DATA")
        assert "AAPL" in summary

    def test_summary_contains_signal_label(self):
        from app.adapters.alternative_data.sec_edgar_adapter import _build_sec_summary
        summary = _build_sec_summary("TSLA", [], "STRONG_SELL")
        assert "강력 매도" in summary

    def test_summary_contains_sell_details(self):
        from app.adapters.alternative_data.sec_edgar_adapter import _build_sec_summary
        filings = [self._make_sell_filing(6_000_000)]
        summary = _build_sec_summary("NVDA", filings, "STRONG_SELL")
        assert "Jane Smith" in summary
        assert "$6,000,000" in summary

    def test_summary_has_disclaimer(self):
        from app.adapters.alternative_data.sec_edgar_adapter import _build_sec_summary
        summary = _build_sec_summary("MSFT", [], "NO_DATA")
        assert "선행 지표" in summary or "투자 판단" in summary

    def test_summary_no_trades_message(self):
        from app.adapters.alternative_data.sec_edgar_adapter import _build_sec_summary
        summary = _build_sec_summary("META", [], "NO_DATA")
        assert "주요 내부자 거래 없음" in summary


class TestSecFilingParsing:
    """_parse_secapi_filing() — sec-api.io 응답 파싱."""

    def _make_secapi_filing(
        self,
        tx_type: str = "S",
        shares: float = 1000.0,
        price: float = 150.0,
        is_deriv: bool = False,
    ) -> dict:
        """sec-api.io 형식의 단일 파일링 픽스처."""
        tx = {
            "transactionCoding": {"transactionType": tx_type},
            "amounts": {
                "shares": shares,
                "pricePerShare": price,
                "acquiredDisposedCode": "D" if tx_type == "S" else "A",
            },
            "postTransactionAmounts": {"sharesOwnedFollowingTransaction": 50000.0},
        }
        if is_deriv:
            return {
                "reportingOwner": {
                    "name": "Alice CEO",
                    "relationship": {"isDirector": True},
                },
                "nonDerivativeTable": {"transactions": []},
                "derivativeTable": {"transactions": [tx]},
            }
        return {
            "reportingOwner": {
                "name": "Alice CEO",
                "relationship": {"officerTitle": "Chief Executive Officer"},
            },
            "nonDerivativeTable": {"transactions": [tx]},
            "derivativeTable": {"transactions": []},
        }

    def test_parse_sell_transaction(self):
        from app.adapters.alternative_data.sec_edgar_adapter import _parse_secapi_filing
        results = _parse_secapi_filing(self._make_secapi_filing("S", 2000, 200.0))
        assert len(results) == 1
        r = results[0]
        assert r["transaction_type"] == "S"
        assert r["shares_traded"] == 2000.0
        assert r["price_per_share"] == 200.0
        assert r["total_value_usd"] == 400_000.0
        assert r["is_derivative"] is False

    def test_parse_buy_transaction(self):
        from app.adapters.alternative_data.sec_edgar_adapter import _parse_secapi_filing
        results = _parse_secapi_filing(self._make_secapi_filing("P", 500, 100.0))
        assert results[0]["transaction_type"] == "P"
        assert results[0]["total_value_usd"] == 50_000.0

    def test_parse_derivative_transaction(self):
        from app.adapters.alternative_data.sec_edgar_adapter import _parse_secapi_filing
        results = _parse_secapi_filing(self._make_secapi_filing("M", 1000, 0.0, is_deriv=True))
        assert len(results) == 1
        assert results[0]["is_derivative"] is True

    def test_reporter_name_extracted(self):
        from app.adapters.alternative_data.sec_edgar_adapter import _parse_secapi_filing
        results = _parse_secapi_filing(self._make_secapi_filing())
        assert results[0]["reporter_name"] == "Alice CEO"

    def test_officer_title_extracted(self):
        from app.adapters.alternative_data.sec_edgar_adapter import _parse_secapi_filing
        results = _parse_secapi_filing(self._make_secapi_filing())
        assert "Chief Executive Officer" in results[0]["reporter_title"]


# ─────────────────────────────────────────────────────────────────────────────
# DART 어댑터 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestDartRatioCalc:
    """_calc_ratios() — 재무 비율 계산 정확성."""

    def test_debt_ratio_calculation(self):
        from app.adapters.alternative_data.dart_adapter import _calc_ratios
        fin = {
            "total_assets": 200_000.0,
            "total_liabilities": 100_000.0,
            "total_equity": 100_000.0,
            "revenue": 50_000.0,
            "operating_income": 10_000.0,
            "net_income": 8_000.0,
        }
        ratios = _calc_ratios(fin)
        assert ratios["debt_ratio_pct"] == 100.0   # 100k/100k * 100

    def test_roe_calculation(self):
        from app.adapters.alternative_data.dart_adapter import _calc_ratios
        fin = {
            "total_equity": 50_000.0,
            "net_income": 10_000.0,
            "total_liabilities": 0,
            "revenue": 100_000.0,
            "operating_income": 15_000.0,
        }
        ratios = _calc_ratios(fin)
        assert ratios["roe_pct"] == 20.0   # 10k/50k * 100

    def test_operating_margin_calculation(self):
        from app.adapters.alternative_data.dart_adapter import _calc_ratios
        fin = {
            "total_equity": 100_000.0,
            "net_income": 5_000.0,
            "total_liabilities": 20_000.0,
            "revenue": 200_000.0,
            "operating_income": 30_000.0,
        }
        ratios = _calc_ratios(fin)
        assert ratios["operating_margin_pct"] == 15.0  # 30k/200k * 100

    def test_safe_division_zero_equity(self):
        """자본이 0일 때 ZeroDivisionError 없이 0.0 반환."""
        from app.adapters.alternative_data.dart_adapter import _calc_ratios
        fin = {
            "total_equity": 0.0,
            "net_income": 5_000.0,
            "total_liabilities": 0.0,
            "revenue": 0.0,
            "operating_income": 0.0,
        }
        ratios = _calc_ratios(fin)
        assert ratios["debt_ratio_pct"] == 0.0
        assert ratios["roe_pct"] == 0.0
        assert ratios["operating_margin_pct"] == 0.0

    def test_zero_revenue_no_crash(self):
        """매출액이 0일 때 영업이익률 계산 안전성."""
        from app.adapters.alternative_data.dart_adapter import _calc_ratios
        fin = {
            "total_equity": 10_000.0,
            "net_income": 0.0,
            "total_liabilities": 5_000.0,
            "revenue": 0.0,
            "operating_income": 1_000.0,
        }
        ratios = _calc_ratios(fin)
        assert ratios["operating_margin_pct"] == 0.0


class TestDartFinancialParsing:
    """_parse_financial_data() — DART API 응답 파싱."""

    def _make_dart_items(self) -> list[dict]:
        """
        DART fnlttSinglAcntAll.json 응답 픽스처.
        thstrm_amount 단위: 원(KRW) — adapter가 /1,000,000 → 백만원으로 변환.
          426,200,000,000원 → 426,200.0백만원 (자산)
          92,000,000,000원 → 92,000.0백만원 (부채)
          334,200,000,000원 → 334,200.0백만원 (자본)
          300,000,000,000원 → 300,000.0백만원 (매출액)
          15,000,000,000원 → 15,000.0백만원 (영업이익)
          12,000,000,000원 → 12,000.0백만원 (당기순이익)
        """
        return [
            {
                "corp_code": "00126380",
                "corp_name": "삼성전자",
                "account_nm": "자산총계",
                "thstrm_amount": "426,200,000,000",
            },
            {
                "corp_code": "00126380",
                "corp_name": "삼성전자",
                "account_nm": "부채총계",
                "thstrm_amount": "92,000,000,000",
            },
            {
                "corp_code": "00126380",
                "corp_name": "삼성전자",
                "account_nm": "자본총계",
                "thstrm_amount": "334,200,000,000",
            },
            {
                "corp_code": "00126380",
                "corp_name": "삼성전자",
                "account_nm": "매출액",
                "thstrm_amount": "300,000,000,000",
            },
            {
                "corp_code": "00126380",
                "corp_name": "삼성전자",
                "account_nm": "영업이익",
                "thstrm_amount": "15,000,000,000",
            },
            {
                "corp_code": "00126380",
                "corp_name": "삼성전자",
                "account_nm": "당기순이익",
                "thstrm_amount": "12,000,000,000",
            },
        ]

    def test_corp_name_extracted(self):
        from app.adapters.alternative_data.dart_adapter import _parse_financial_data
        corp_name, _ = _parse_financial_data(self._make_dart_items())
        assert corp_name == "삼성전자"

    def test_total_assets_parsed(self):
        from app.adapters.alternative_data.dart_adapter import _parse_financial_data
        _, fin = _parse_financial_data(self._make_dart_items())
        # 426,200,000원 → 426,200.0 백만원
        assert fin["total_assets"] == 426200.0

    def test_revenue_parsed_with_comma(self):
        from app.adapters.alternative_data.dart_adapter import _parse_financial_data
        _, fin = _parse_financial_data(self._make_dart_items())
        assert fin["revenue"] == 300000.0

    def test_all_six_fields_present(self):
        from app.adapters.alternative_data.dart_adapter import _parse_financial_data
        _, fin = _parse_financial_data(self._make_dart_items())
        for key in ["total_assets", "total_liabilities", "total_equity",
                    "revenue", "operating_income", "net_income"]:
            assert key in fin, f"Missing key: {key}"

    def test_empty_list_returns_empty(self):
        from app.adapters.alternative_data.dart_adapter import _parse_financial_data
        corp_name, fin = _parse_financial_data([])
        assert corp_name == ""
        assert fin == {}

    def test_unknown_account_ignored(self):
        """매핑에 없는 계정과목은 무시."""
        from app.adapters.alternative_data.dart_adapter import _parse_financial_data
        items = [
            {"corp_code": "99999999", "corp_name": "테스트", "account_nm": "미인식계정", "thstrm_amount": "999"}
        ]
        _, fin = _parse_financial_data(items)
        assert fin == {}


class TestDartSummaryBuilding:
    """_build_dart_summary() — LLM 프롬프트 주입용 텍스트."""

    def _sample_financials(self) -> dict:
        return {
            "total_assets": 426_200.0,
            "total_liabilities": 92_000.0,
            "total_equity": 334_200.0,
            "revenue": 300_000.0,
            "operating_income": 15_000.0,
            "net_income": 12_000.0,
        }

    def test_summary_contains_corp_name(self):
        from app.adapters.alternative_data.dart_adapter import _build_dart_summary, _calc_ratios
        fin = self._sample_financials()
        ratios = _calc_ratios(fin)
        summary = _build_dart_summary("005930", "삼성전자", "2024", fin, ratios)
        assert "삼성전자" in summary

    def test_summary_contains_year(self):
        from app.adapters.alternative_data.dart_adapter import _build_dart_summary, _calc_ratios
        fin = self._sample_financials()
        ratios = _calc_ratios(fin)
        summary = _build_dart_summary("005930", "삼성전자", "2024", fin, ratios)
        assert "2024" in summary

    def test_summary_contains_revenue_section(self):
        from app.adapters.alternative_data.dart_adapter import _build_dart_summary, _calc_ratios
        fin = self._sample_financials()
        ratios = _calc_ratios(fin)
        summary = _build_dart_summary("005930", "삼성전자", "2024", fin, ratios)
        assert "매출액" in summary

    def test_summary_contains_roe(self):
        from app.adapters.alternative_data.dart_adapter import _build_dart_summary, _calc_ratios
        fin = self._sample_financials()
        ratios = _calc_ratios(fin)
        summary = _build_dart_summary("005930", "삼성전자", "2024", fin, ratios)
        assert "ROE" in summary

    def test_debt_ratio_warning_high(self):
        """부채비율 200% 초과 시 경고 포함."""
        from app.adapters.alternative_data.dart_adapter import _build_dart_summary, _calc_ratios
        fin = {
            "total_assets": 300_000.0,
            "total_liabilities": 240_000.0,
            "total_equity": 60_000.0,
            "revenue": 100_000.0,
            "operating_income": -5_000.0,
            "net_income": -3_000.0,
        }
        ratios = _calc_ratios(fin)
        summary = _build_dart_summary("000000", "위험기업", "2024", fin, ratios)
        assert "부채비율" in summary

    def test_unit_conversion_tril(self):
        """1조원 이상 → '조원' 단위 표시."""
        from app.adapters.alternative_data.dart_adapter import _build_dart_summary, _calc_ratios
        fin = {
            "total_assets": 2_000_000.0,   # 2조원 = 2,000,000 백만원
            "total_liabilities": 500_000.0,
            "total_equity": 1_500_000.0,
            "revenue": 1_000_000.0,
            "operating_income": 150_000.0,
            "net_income": 100_000.0,
        }
        ratios = _calc_ratios(fin)
        summary = _build_dart_summary("005380", "현대자동차", "2024", fin, ratios)
        assert "조원" in summary


# ─────────────────────────────────────────────────────────────────────────────
# Redis 캐시 테스트 (Mock Redis)
# ─────────────────────────────────────────────────────────────────────────────

class TestAlternativeDataCache:
    """AlternativeDataCache — set/get/track 동작."""

    def _make_cache_with_mock_redis(self):
        """Mock Redis를 주입한 캐시 인스턴스 생성."""
        from app.adapters.alternative_data.redis_cache import AlternativeDataCache
        cache = AlternativeDataCache.__new__(AlternativeDataCache)
        mock_redis = MagicMock()
        # get 기본 반환값: None (캐시 미스)
        mock_redis.get.return_value = None
        cache._redis = mock_redis
        return cache, mock_redis

    def test_set_sec_data_calls_setex(self):
        cache, mock_redis = self._make_cache_with_mock_redis()
        data = {"ticker": "AAPL", "signal": "BUY"}
        cache.set_sec_data("AAPL", data)
        mock_redis.setex.assert_called_once()
        key, ttl, value = mock_redis.setex.call_args[0]
        assert "AAPL" in key
        assert ttl == 21600   # SEC_CACHE_TTL

    def test_get_sec_data_returns_none_on_miss(self):
        cache, mock_redis = self._make_cache_with_mock_redis()
        mock_redis.get.return_value = None
        result = cache.get_sec_data("AAPL")
        assert result is None

    def test_get_sec_data_deserializes_json(self):
        cache, mock_redis = self._make_cache_with_mock_redis()
        payload = {"ticker": "AAPL", "signal": "STRONG_SELL"}
        mock_redis.get.return_value = json.dumps(payload)
        result = cache.get_sec_data("AAPL")
        assert result == payload

    def test_set_dart_data_uses_longer_ttl(self):
        cache, mock_redis = self._make_cache_with_mock_redis()
        cache.set_dart_data("005930", {"ticker": "005930"})
        key, ttl, _ = mock_redis.setex.call_args[0]
        assert ttl == 86400   # DART_CACHE_TTL (24h > 6h)

    def test_track_ticker_calls_sadd(self):
        cache, mock_redis = self._make_cache_with_mock_redis()
        cache.track_ticker("NVDA", "sec")
        mock_redis.sadd.assert_called_once_with("alt_data:watched:sec", "NVDA")

    def test_track_ticker_uppercases_key(self):
        cache, mock_redis = self._make_cache_with_mock_redis()
        cache.track_ticker("nvda", "sec")
        mock_redis.sadd.assert_called_with("alt_data:watched:sec", "NVDA")

    def test_get_watched_tickers_returns_set_members(self):
        cache, mock_redis = self._make_cache_with_mock_redis()
        mock_redis.smembers.return_value = {"AAPL", "MSFT", "NVDA"}
        result = cache.get_watched_tickers("sec")
        assert set(result) == {"AAPL", "MSFT", "NVDA"}

    def test_redis_none_returns_gracefully(self):
        """Redis 연결 실패 시 모든 메서드가 조용히 실패."""
        from app.adapters.alternative_data.redis_cache import AlternativeDataCache
        cache = AlternativeDataCache.__new__(AlternativeDataCache)
        cache._redis = None   # 연결 없음
        # 어떤 예외도 발생하지 않아야 함
        cache.set_sec_data("AAPL", {"test": 1})
        result = cache.get_sec_data("AAPL")
        assert result is None
        cache.track_ticker("AAPL", "sec")
        tickers = cache.get_watched_tickers("sec")
        assert tickers == []


# ─────────────────────────────────────────────────────────────────────────────
# 프롬프트 주입 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestFormatAlternativeData:
    """_format_alternative_data() — LLM 프롬프트 생성."""

    def _make_alt_data(
        self,
        sec_summary: str = "[SEC EDGAR Form 4 내부자 거래 — AAPL]\n시그널: BUY",
        dart_summary: str = "[DART 재무공시 2024년 — 삼성전자(005930)]",
    ) -> dict:
        return {
            "sec_insider": {
                "AAPL": {"ticker": "AAPL", "signal": "BUY", "summary": sec_summary},
            },
            "dart_financials": {
                "005930": {"ticker": "005930", "corp_name": "삼성전자", "summary": dart_summary},
            },
        }

    def test_returns_empty_string_when_no_data(self):
        from app.services.ai.prompt_builder import _format_alternative_data
        assert _format_alternative_data(None) == ""
        assert _format_alternative_data({}) == ""

    def test_returns_empty_when_both_empty(self):
        from app.services.ai.prompt_builder import _format_alternative_data
        result = _format_alternative_data({"sec_insider": {}, "dart_financials": {}})
        assert result == ""

    def test_sec_header_present(self):
        from app.services.ai.prompt_builder import _format_alternative_data
        result = _format_alternative_data(self._make_alt_data())
        assert "대안 데이터" in result

    def test_sec_summary_injected(self):
        from app.services.ai.prompt_builder import _format_alternative_data
        result = _format_alternative_data(self._make_alt_data())
        assert "AAPL" in result
        assert "BUY" in result

    def test_dart_summary_injected(self):
        from app.services.ai.prompt_builder import _format_alternative_data
        result = _format_alternative_data(self._make_alt_data())
        assert "삼성전자" in result
        assert "005930" in result

    def test_only_sec_data(self):
        """DART 없이 SEC만 있는 경우."""
        from app.services.ai.prompt_builder import _format_alternative_data
        alt_data = {
            "sec_insider": {"TSLA": {"ticker": "TSLA", "signal": "STRONG_SELL",
                                     "summary": "TSLA 내부자 매도"}},
            "dart_financials": {},
        }
        result = _format_alternative_data(alt_data)
        assert "TSLA" in result
        assert result != ""

    def test_only_dart_data(self):
        """SEC 없이 DART만 있는 경우 — 헤더 한 번만 출력."""
        from app.services.ai.prompt_builder import _format_alternative_data
        alt_data = {
            "sec_insider": {},
            "dart_financials": {
                "005930": {"ticker": "005930", "corp_name": "삼성전자",
                           "summary": "삼성전자 재무공시"}
            },
        }
        result = _format_alternative_data(alt_data)
        assert "삼성전자" in result
        # 헤더가 두 번 포함되지 않아야 함
        assert result.count("대안 데이터") <= 1

    def test_multiple_tickers_all_injected(self):
        """복수 티커 모두 프롬프트에 포함."""
        from app.services.ai.prompt_builder import _format_alternative_data
        alt_data = {
            "sec_insider": {
                "AAPL": {"ticker": "AAPL", "signal": "BUY", "summary": "AAPL 매수"},
                "MSFT": {"ticker": "MSFT", "signal": "NEUTRAL", "summary": "MSFT 중립"},
            },
            "dart_financials": {},
        }
        result = _format_alternative_data(alt_data)
        assert "AAPL" in result
        assert "MSFT" in result


# ─────────────────────────────────────────────────────────────────────────────
# PortfolioContext 데이터클래스 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestPortfolioContextAlternativeData:
    """PortfolioContext에 alternative_data 필드 추가 확인."""

    def test_alternative_data_defaults_to_none(self):
        """alternative_data 미전달 시 None (하위 호환성)."""
        from app.services.ai.prompt_builder import PortfolioContext
        ctx = PortfolioContext(
            portfolio_name="Test",
            total_cost_krw=Decimal("1000000"),
            total_value_krw=Decimal("1100000"),
            total_return_pct=Decimal("10"),
            price_contribution_krw=Decimal("100000"),
            fx_contribution_krw=Decimal("0"),
            usd_krw_rate=Decimal("1380"),
            rate_source="yfinance",
            holdings_summary=[],
            optimization_result=None,
        )
        assert ctx.alternative_data is None

    def test_alternative_data_can_be_set(self):
        from app.services.ai.prompt_builder import PortfolioContext
        alt = {"sec_insider": {"AAPL": {}}, "dart_financials": {}}
        ctx = PortfolioContext(
            portfolio_name="Test",
            total_cost_krw=Decimal("1000000"),
            total_value_krw=Decimal("1100000"),
            total_return_pct=Decimal("10"),
            price_contribution_krw=Decimal("100000"),
            fx_contribution_krw=Decimal("0"),
            usd_krw_rate=Decimal("1380"),
            rate_source="yfinance",
            holdings_summary=[],
            optimization_result=None,
            alternative_data=alt,
        )
        assert ctx.alternative_data == alt

    def test_prompt_includes_alt_data_when_set(self):
        """alternative_data가 있으면 최종 프롬프트 문자열에 포함."""
        from app.services.ai.prompt_builder import PortfolioContext, build_portfolio_report_prompt
        from datetime import datetime
        alt = {
            "sec_insider": {
                "AAPL": {"ticker": "AAPL", "signal": "BUY", "summary": "[SEC] AAPL 매수 시그널"},
            },
            "dart_financials": {},
        }
        ctx = PortfolioContext(
            portfolio_name="My Portfolio",
            total_cost_krw=Decimal("5000000"),
            total_value_krw=Decimal("5500000"),
            total_return_pct=Decimal("10"),
            price_contribution_krw=Decimal("500000"),
            fx_contribution_krw=Decimal("0"),
            usd_krw_rate=Decimal("1380"),
            rate_source="yfinance",
            holdings_summary=[],
            optimization_result=None,
            alternative_data=alt,
        )
        messages = build_portfolio_report_prompt(ctx, "포트폴리오 분석해줘", "2025-01-01 09:00")
        final_user = messages[2]["parts"][0]
        assert "AAPL" in final_user
        assert "매수 시그널" in final_user


# ─────────────────────────────────────────────────────────────────────────────
# _fetch_alternative_data_safe() Celery 헬퍼 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestFetchAlternativeDataSafe:
    """_fetch_alternative_data_safe() — Celery 태스크 헬퍼."""

    def _make_context(self, holdings: list[dict]) -> dict:
        return {
            "portfolio_name": "Test Portfolio",
            "holdings_summary": holdings,
            "total_cost_krw": "5000000",
            "total_value_krw": "5500000",
            "total_return_pct": "10.0",
            "price_contribution_krw": "500000",
            "fx_contribution_krw": "0",
            "usd_krw_rate": "1380",
            "rate_source": "yfinance",
        }

    def _make_holding(self, ticker: str, currency: str = "USD") -> dict:
        return {
            "ticker": ticker,
            "name": ticker,
            "quantity": "10",
            "avg_cost": "100.00",
            "current_price": "110.00",
            "currency": currency,
            "price_return_pct": 10.0,
            "fx_return_pct": 0.0,
            "total_return_pct": 10.0,
        }

    def test_us_ticker_reads_sec_cache(self):
        """US 티커는 SEC 캐시에서 읽어야 함."""
        from app.worker.tasks.ai_report_tasks import _fetch_alternative_data_safe

        sec_data = {"ticker": "AAPL", "signal": "BUY", "filings": [], "summary": "test"}
        mock_cache = MagicMock()
        mock_cache.get_sec_data.return_value = sec_data
        mock_cache.get_dart_data.return_value = None

        with patch(
            "app.worker.tasks.ai_report_tasks.alt_data_cache" ,
            mock_cache,
            create=True,
        ):
            with patch(
                "app.adapters.alternative_data.redis_cache.alt_data_cache",
                mock_cache,
            ):
                ctx = self._make_context([self._make_holding("AAPL")])
                # Import after patching
                import importlib
                import app.worker.tasks.ai_report_tasks as task_mod
                with patch.object(task_mod, "_fetch_alternative_data_safe",
                                  wraps=task_mod._fetch_alternative_data_safe):
                    pass

        # 직접 캐시 모킹으로 테스트
        with patch("app.adapters.alternative_data.redis_cache.alt_data_cache", mock_cache):
            # redis_cache 모듈의 싱글턴을 대체
            import app.adapters.alternative_data.redis_cache as cache_mod
            original = cache_mod.alt_data_cache
            cache_mod.alt_data_cache = mock_cache
            try:
                ctx = self._make_context([self._make_holding("AAPL")])
                result = _fetch_alternative_data_safe(ctx)
                assert result is not None
                assert "AAPL" in result["sec_insider"]
            finally:
                cache_mod.alt_data_cache = original

    def test_kr_ticker_reads_dart_cache(self):
        """6자리 KR 티커는 DART 캐시에서 읽어야 함."""
        from app.worker.tasks.ai_report_tasks import _fetch_alternative_data_safe

        dart_data = {
            "ticker": "005930", "corp_name": "삼성전자",
            "bsns_year": "2024", "summary": "test",
        }
        mock_cache = MagicMock()
        mock_cache.get_sec_data.return_value = None
        mock_cache.get_dart_data.return_value = dart_data

        import app.adapters.alternative_data.redis_cache as cache_mod
        original = cache_mod.alt_data_cache
        cache_mod.alt_data_cache = mock_cache
        try:
            ctx = self._make_context([self._make_holding("005930", "KRW")])
            result = _fetch_alternative_data_safe(ctx)
            assert result is not None
            assert "005930" in result["dart_financials"]
        finally:
            cache_mod.alt_data_cache = original

    def test_cache_miss_registers_ticker(self):
        """캐시 미스 시 track_ticker()로 등록해야 함."""
        from app.worker.tasks.ai_report_tasks import _fetch_alternative_data_safe

        mock_cache = MagicMock()
        mock_cache.get_sec_data.return_value = None   # 캐시 미스
        mock_cache.get_dart_data.return_value = None  # 캐시 미스

        import app.adapters.alternative_data.redis_cache as cache_mod
        original = cache_mod.alt_data_cache
        cache_mod.alt_data_cache = mock_cache
        try:
            ctx = self._make_context([
                self._make_holding("MSFT"),
                self._make_holding("005380", "KRW"),
            ])
            _fetch_alternative_data_safe(ctx)
            # track_ticker 호출 확인 (캐시 미스 등록)
            assert mock_cache.track_ticker.called
        finally:
            cache_mod.alt_data_cache = original

    def test_returns_none_when_all_cache_miss(self):
        """모든 티커 캐시 미스 → None 반환."""
        from app.worker.tasks.ai_report_tasks import _fetch_alternative_data_safe

        mock_cache = MagicMock()
        mock_cache.get_sec_data.return_value = None
        mock_cache.get_dart_data.return_value = None

        import app.adapters.alternative_data.redis_cache as cache_mod
        original = cache_mod.alt_data_cache
        cache_mod.alt_data_cache = mock_cache
        try:
            ctx = self._make_context([self._make_holding("AAPL")])
            result = _fetch_alternative_data_safe(ctx)
            assert result is None
        finally:
            cache_mod.alt_data_cache = original

    def test_mixed_us_kr_holdings(self):
        """US + KR 혼합 포트폴리오에서 각각 올바른 캐시 조회."""
        from app.worker.tasks.ai_report_tasks import _fetch_alternative_data_safe

        sec_data = {"ticker": "AAPL", "signal": "BUY", "filings": [], "summary": "sec_test"}
        dart_data = {"ticker": "005930", "corp_name": "삼성전자", "summary": "dart_test"}

        mock_cache = MagicMock()
        mock_cache.get_sec_data.return_value = sec_data
        mock_cache.get_dart_data.return_value = dart_data

        import app.adapters.alternative_data.redis_cache as cache_mod
        original = cache_mod.alt_data_cache
        cache_mod.alt_data_cache = mock_cache
        try:
            ctx = self._make_context([
                self._make_holding("AAPL", "USD"),
                self._make_holding("005930", "KRW"),
            ])
            result = _fetch_alternative_data_safe(ctx)
            assert result is not None
            assert "AAPL" in result["sec_insider"]
            assert "005930" in result["dart_financials"]
        finally:
            cache_mod.alt_data_cache = original

    def test_exception_returns_none_silently(self):
        """캐시 접근 중 예외 → None 반환, 예외 전파 없음."""
        from app.worker.tasks.ai_report_tasks import _fetch_alternative_data_safe

        mock_cache = MagicMock()
        mock_cache.get_sec_data.side_effect = RuntimeError("Redis connection lost")

        import app.adapters.alternative_data.redis_cache as cache_mod
        original = cache_mod.alt_data_cache
        cache_mod.alt_data_cache = mock_cache
        try:
            ctx = self._make_context([self._make_holding("AAPL")])
            result = _fetch_alternative_data_safe(ctx)
            assert result is None
        finally:
            cache_mod.alt_data_cache = original

    def test_empty_holdings_returns_none(self):
        """보유 종목 없음 → None 반환."""
        from app.worker.tasks.ai_report_tasks import _fetch_alternative_data_safe
        ctx = self._make_context([])
        result = _fetch_alternative_data_safe(ctx)
        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# 티커 분류 로직 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestIsKrTicker:
    """_is_kr_ticker() — KR / US 티커 판별."""

    def test_six_digit_kr(self):
        from app.worker.tasks.ai_report_tasks import _is_kr_ticker
        assert _is_kr_ticker("005930") is True

    def test_kr_with_ks_suffix(self):
        from app.worker.tasks.ai_report_tasks import _is_kr_ticker
        assert _is_kr_ticker("005930.KS") is True

    def test_kr_with_kq_suffix(self):
        from app.worker.tasks.ai_report_tasks import _is_kr_ticker
        assert _is_kr_ticker("035420.KQ") is True

    def test_us_alpha_ticker(self):
        from app.worker.tasks.ai_report_tasks import _is_kr_ticker
        assert _is_kr_ticker("AAPL") is False

    def test_us_ticker_with_numbers(self):
        from app.worker.tasks.ai_report_tasks import _is_kr_ticker
        assert _is_kr_ticker("BRK.B") is False

    def test_five_digit_not_kr(self):
        """5자리 숫자는 KR 코드 아님."""
        from app.worker.tasks.ai_report_tasks import _is_kr_ticker
        assert _is_kr_ticker("12345") is False

    def test_seven_digit_not_kr(self):
        """7자리 숫자는 KR 코드 아님."""
        from app.worker.tasks.ai_report_tasks import _is_kr_ticker
        assert _is_kr_ticker("1234567") is False

    def test_empty_string(self):
        from app.worker.tasks.ai_report_tasks import _is_kr_ticker
        assert _is_kr_ticker("") is False
