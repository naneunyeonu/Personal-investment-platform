"""
ML 포트폴리오 최적화 파이프라인 유닛 테스트

테스트 범위:
1. 티커 변환기 — yfinance 심볼 변환 로직
2. 최적화 수치 연산 — _optimize_sync 합성 데이터 기반 정확성 검증
3. 자연어 요약 생성 — LLM 프롬프트 주입용 텍스트 구조 검증
4. 엣지 케이스 — 단일 종목·빈 데이터·실패 처리
5. 비동기 파이프라인 — run_portfolio_optimization mocked 통합 테스트
6. Celery 태스크 통합 — ML 결과가 PortfolioContext에 주입되는지 확인
7. 프롬프트 주입 — optimization_result가 messages[2]에 포함되는지 검증

실제 yfinance / 네트워크 호출: mock 처리 (유닛 테스트)
"""

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest


# ─────────────────────────────────────────────────────────────────────────────
# 공용 픽스처
# ─────────────────────────────────────────────────────────────────────────────

def _make_synthetic_prices(tickers: list[str], n: int = 504) -> pd.DataFrame:
    """
    기하 브라운 운동(GBM) 기반 합성 종가 데이터 생성.
    n=504 ≈ 2년치 거래일 (최적화 안정성에 충분한 샘플)
    """
    np.random.seed(42)
    data = {}
    for i, t in enumerate(tickers):
        drift = 0.001 + i * 0.0002
        vol = 0.015 + i * 0.002
        log_returns = np.random.normal(drift, vol, n)
        prices = 100.0 * np.exp(np.cumsum(log_returns))
        data[t] = prices
    idx = pd.date_range("2023-01-01", periods=n, freq="B")
    return pd.DataFrame(data, index=idx)


def _make_synthetic_returns(tickers: list[str], n: int = 504) -> pd.DataFrame:
    prices = _make_synthetic_prices(tickers, n)
    return prices.pct_change().dropna()


# ─────────────────────────────────────────────────────────────────────────────
# 1. 티커 변환기 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestYfinanceTickerConverter:

    def test_global_ticker_unchanged(self):
        """미국 주식 티커는 그대로 유지되어야 함"""
        from app.services.ml.historical_data import _to_yf_ticker
        assert _to_yf_ticker("AAPL") == "AAPL"
        assert _to_yf_ticker("MSFT") == "MSFT"
        assert _to_yf_ticker("GOOGL") == "GOOGL"

    def test_6digit_ticker_gets_ks_suffix(self):
        """6자리 숫자 KRX 코드에 .KS 접미사가 붙어야 함"""
        from app.services.ml.historical_data import _to_yf_ticker
        assert _to_yf_ticker("005930") == "005930.KS"  # 삼성전자
        assert _to_yf_ticker("000660") == "000660.KS"  # SK하이닉스

    def test_ks_ticker_already_has_suffix(self):
        """.KS 접미사가 이미 있으면 중복 추가하지 않아야 함"""
        from app.services.ml.historical_data import _to_yf_ticker
        assert _to_yf_ticker("005930.KS") == "005930.KS"

    def test_kq_ticker_preserved(self):
        """.KQ(코스닥) 접미사도 그대로 유지되어야 함"""
        from app.services.ml.historical_data import _to_yf_ticker
        assert _to_yf_ticker("035420.KQ") == "035420.KQ"

    def test_etf_ticker_unchanged(self):
        """ETF 티커는 변환하지 않아야 함"""
        from app.services.ml.historical_data import _to_yf_ticker
        assert _to_yf_ticker("SPY") == "SPY"
        assert _to_yf_ticker("QQQ") == "QQQ"


# ─────────────────────────────────────────────────────────────────────────────
# 2. 최적화 수치 연산 테스트 (_optimize_sync)
# ─────────────────────────────────────────────────────────────────────────────

class TestOptimizeSyncCalculations:

    def setup_method(self):
        self.tickers = ["AAPL", "MSFT", "GOOGL"]
        self.returns = _make_synthetic_returns(self.tickers)
        self.current_weights = {"AAPL": 0.5, "MSFT": 0.3, "GOOGL": 0.2}

    def test_result_status_is_success(self):
        """정상 데이터에서 status='success'를 반환해야 함"""
        from app.services.ml.optimizer import _optimize_sync
        result = _optimize_sync(
            self.returns, self.tickers, self.current_weights, 0.035
        )
        assert result["status"] == "success"

    def test_min_volatility_weights_sum_to_one(self):
        """최소 변동성 포트폴리오의 비중 합계가 1.0이어야 함"""
        from app.services.ml.optimizer import _optimize_sync
        result = _optimize_sync(
            self.returns, self.tickers, self.current_weights, 0.035
        )
        assert "error" not in result["min_volatility"]
        total = sum(result["min_volatility"]["weights"].values())
        assert abs(total - 1.0) < 0.01, f"비중 합계 오류: {total}"

    def test_max_sharpe_weights_sum_to_one(self):
        """최대 샤프 비율 포트폴리오의 비중 합계가 1.0이어야 함"""
        from app.services.ml.optimizer import _optimize_sync
        result = _optimize_sync(
            self.returns, self.tickers, self.current_weights, 0.035
        )
        assert "error" not in result["max_sharpe"]
        total = sum(result["max_sharpe"]["weights"].values())
        assert abs(total - 1.0) < 0.01

    def test_hrp_weights_sum_to_one(self):
        """HRP 포트폴리오의 비중 합계가 1.0이어야 함"""
        from app.services.ml.optimizer import _optimize_sync
        result = _optimize_sync(
            self.returns, self.tickers, self.current_weights, 0.035
        )
        assert "error" not in result["hrp"]
        total = sum(result["hrp"]["weights"].values())
        assert abs(total - 1.0) < 0.01

    def test_all_weights_non_negative(self):
        """Long-only 제약: 모든 비중이 0 이상이어야 함"""
        from app.services.ml.optimizer import _optimize_sync
        result = _optimize_sync(
            self.returns, self.tickers, self.current_weights, 0.035
        )
        for strategy in ("min_volatility", "max_sharpe", "hrp"):
            if "error" not in result.get(strategy, {}):
                for ticker, w in result[strategy]["weights"].items():
                    assert w >= -0.001, f"{strategy}/{ticker} 비중 음수: {w}"

    def test_min_volatility_lower_than_max_return(self):
        """최소 변동성 포트폴리오의 변동성이 최대 수익률 포트폴리오보다 낮아야 함"""
        from app.services.ml.optimizer import _optimize_sync
        result = _optimize_sync(
            self.returns, self.tickers, self.current_weights, 0.035
        )
        mv = result.get("min_volatility", {})
        er = result.get("max_return", {})
        if "error" not in mv and "error" not in er:
            assert mv["annual_volatility"] <= er["annual_volatility"] + 0.01, (
                f"MVP 변동성({mv['annual_volatility']:.4f})이 "
                f"ER 변동성({er['annual_volatility']:.4f})보다 높음"
            )

    def test_current_performance_included(self):
        """현재 포트폴리오 성과 기준선이 포함되어야 함"""
        from app.services.ml.optimizer import _optimize_sync
        result = _optimize_sync(
            self.returns, self.tickers, self.current_weights, 0.035
        )
        curr = result.get("current_performance", {})
        assert "error" not in curr
        assert "expected_annual_return" in curr
        assert "annual_volatility" in curr
        assert "sharpe_ratio" in curr

    def test_covariance_period_returned(self):
        """공분산 추정 기간(연 단위)이 결과에 포함되어야 함"""
        from app.services.ml.optimizer import _optimize_sync
        result = _optimize_sync(
            self.returns, self.tickers, self.current_weights, 0.035
        )
        assert "covariance_period_years" in result
        assert result["covariance_period_years"] > 0


# ─────────────────────────────────────────────────────────────────────────────
# 3. 자연어 요약 생성 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildOptimizationSummary:

    def _run_and_get_summary(self, tickers=None):
        from app.services.ml.optimizer import _optimize_sync
        t = tickers or ["AAPL", "MSFT", "GOOGL"]
        returns = _make_synthetic_returns(t)
        weights = {ticker: 1 / len(t) for ticker in t}
        result = _optimize_sync(returns, t, weights, 0.035)
        return result.get("summary", "")

    def test_summary_is_non_empty_string(self):
        """summary 필드는 비어 있지 않은 문자열이어야 함"""
        summary = self._run_and_get_summary()
        assert isinstance(summary, str)
        assert len(summary) > 100

    def test_summary_contains_mvp_section(self):
        """MVP(최소 변동성) 섹션이 summary에 포함되어야 함"""
        summary = self._run_and_get_summary()
        assert "최소 변동성" in summary or "MVP" in summary

    def test_summary_contains_msr_section(self):
        """MSR(최대 샤프 비율) 섹션이 summary에 포함되어야 함"""
        summary = self._run_and_get_summary()
        assert "샤프 비율" in summary or "MSR" in summary

    def test_summary_contains_hrp_section(self):
        """HRP 섹션이 summary에 포함되어야 함"""
        summary = self._run_and_get_summary()
        assert "HRP" in summary or "리스크 패리티" in summary

    def test_summary_contains_disclaimer(self):
        """면책 고지가 summary에 포함되어야 함 (투자자 보호)"""
        summary = self._run_and_get_summary()
        assert "과거 수익률" in summary or "보장하지 않습니다" in summary

    def test_summary_injected_into_prompt(self):
        """optimization_result.summary가 Gemini 프롬프트 messages[2]에 포함되어야 함"""
        from app.services.ai.prompt_builder import PortfolioContext, build_portfolio_report_prompt

        opt_result = {
            "status": "success",
            "summary": "▶ 시뮬레이션 ① 최소 변동성\n  • 예상 연 수익률: +8.50%",
        }
        ctx = PortfolioContext(
            portfolio_name="테스트",
            total_cost_krw=Decimal("10000000"),
            total_value_krw=Decimal("11000000"),
            total_return_pct=Decimal("10.00"),
            price_contribution_krw=Decimal("900000"),
            fx_contribution_krw=Decimal("100000"),
            usd_krw_rate=Decimal("1380"),
            rate_source="yfinance",
            holdings_summary=[],
            optimization_result=opt_result,
        )
        msgs = build_portfolio_report_prompt(ctx, "분석해주세요", "2026-05-27")
        last_msg = msgs[2]["parts"][0]

        assert "최소 변동성" in last_msg, "MVP 섹션이 프롬프트에 없음"
        assert "8.50%" in last_msg, "수치가 프롬프트에 없음"

    def test_no_optimization_omitted_from_prompt(self):
        """optimization_result=None이면 ML 섹션이 프롬프트에 없어야 함"""
        from app.services.ai.prompt_builder import PortfolioContext, build_portfolio_report_prompt

        ctx = PortfolioContext(
            portfolio_name="테스트",
            total_cost_krw=Decimal("5000000"),
            total_value_krw=Decimal("5500000"),
            total_return_pct=Decimal("10.00"),
            price_contribution_krw=Decimal("500000"),
            fx_contribution_krw=Decimal("0"),
            usd_krw_rate=Decimal("1380"),
            rate_source="yfinance",
            holdings_summary=[],
            optimization_result=None,
        )
        msgs = build_portfolio_report_prompt(ctx, "분석", "2026-05-27")
        last_msg = msgs[2]["parts"][0]
        assert "PyPortfolioOpt" not in last_msg
        assert "ML 포트폴리오 최적화" not in last_msg


# ─────────────────────────────────────────────────────────────────────────────
# 4. 엣지 케이스 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestEdgeCases:

    def test_single_ticker_returns_failed(self):
        """단일 종목 포트폴리오는 분산 최적화 불가 → status='failed'"""
        result = asyncio.run(
            _run_optimization_with_mock_prices(
                tickers=["AAPL"],
                current_weights={"AAPL": 1.0},
                mock_df=pd.DataFrame(),  # 단일 종목은 fetch 전에 걸러짐
            )
        )
        assert result["status"] == "failed"

    def test_empty_dataframe_returns_failed(self):
        """빈 DataFrame 반환 시 status='failed'"""
        result = asyncio.run(
            _run_optimization_with_mock_prices(
                tickers=["AAPL", "MSFT"],
                current_weights={"AAPL": 0.6, "MSFT": 0.4},
                mock_df=pd.DataFrame(),
            )
        )
        assert result["status"] == "failed"

    def test_insufficient_data_returns_failed(self):
        """관측치가 30일 미만이면 status='failed'"""
        tiny_df = _make_synthetic_prices(["AAPL", "MSFT"], n=10)
        result = asyncio.run(
            _run_optimization_with_mock_prices(
                tickers=["AAPL", "MSFT"],
                current_weights={"AAPL": 0.6, "MSFT": 0.4},
                mock_df=tiny_df,
            )
        )
        assert result["status"] == "failed"

    def test_failed_result_has_summary(self):
        """실패 케이스도 summary 필드를 포함해야 함 (LLM에 전달)"""
        from app.services.ml.optimizer import _failed_result, _single_asset_result
        assert "summary" in _failed_result("테스트 오류")
        assert "summary" in _single_asset_result(["AAPL"])

    def test_optimization_does_not_raise_on_partial_failure(self):
        """일부 최적화 전략 실패 시에도 전체 결과를 반환해야 함"""
        # 2종목으로 테스트 (max_return이 solver 문제로 실패할 수 있음)
        from app.services.ml.optimizer import _optimize_sync
        tickers = ["AAPL", "MSFT"]
        returns = _make_synthetic_returns(tickers)
        weights = {"AAPL": 0.6, "MSFT": 0.4}
        result = _optimize_sync(returns, tickers, weights, 0.035)
        # 예외 없이 반환되어야 함
        assert isinstance(result, dict)
        assert "summary" in result


# ─────────────────────────────────────────────────────────────────────────────
# 5. 비동기 파이프라인 통합 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestRunPortfolioOptimizationAsync:

    def test_run_optimization_with_mocked_prices_success(self):
        """mocked 가격 데이터로 전체 비동기 파이프라인이 성공해야 함"""
        mock_df = _make_synthetic_prices(["AAPL", "MSFT", "GOOGL"], n=504)
        result = asyncio.run(
            _run_optimization_with_mock_prices(
                tickers=["AAPL", "MSFT", "GOOGL"],
                current_weights={"AAPL": 0.5, "MSFT": 0.3, "GOOGL": 0.2},
                mock_df=mock_df,
            )
        )
        assert result["status"] == "success"
        assert "min_volatility" in result
        assert "max_sharpe" in result
        assert "hrp" in result
        assert "summary" in result
        assert len(result["summary"]) > 50

    def test_tickers_field_matches_available_data(self):
        """결과의 tickers 필드가 실제 데이터 수집 성공 종목만 포함해야 함"""
        mock_df = _make_synthetic_prices(["AAPL", "MSFT"], n=504)
        result = asyncio.run(
            _run_optimization_with_mock_prices(
                tickers=["AAPL", "MSFT", "UNKNOWN_TICKER"],  # UNKNOWN은 데이터 없음
                current_weights={"AAPL": 0.5, "MSFT": 0.4, "UNKNOWN_TICKER": 0.1},
                mock_df=mock_df,  # UNKNOWN_TICKER 컬럼 없음
            )
        )
        # mock_df에 없는 종목은 제외되어 2종목으로 최적화
        if result["status"] == "success":
            assert "UNKNOWN_TICKER" not in result["tickers"]


# ─────────────────────────────────────────────────────────────────────────────
# 6. Celery 태스크 ML 주입 통합 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestCeleryTaskMLInjection:

    def test_ml_optimization_safe_with_valid_holdings(self):
        """유효한 holdings에서 ML 최적화 결과를 반환해야 함"""
        from app.worker.tasks.ai_report_tasks import _run_ml_optimization_safe

        mock_df = _make_synthetic_prices(["AAPL", "MSFT"], n=504)

        context_dict = {
            "portfolio_name": "테스트",
            "total_cost_krw": "2000000",
            "total_value_krw": "2200000",
            "total_return_pct": "10.00",
            "price_contribution_krw": "180000",
            "fx_contribution_krw": "20000",
            "usd_krw_rate": "1380",
            "rate_source": "yfinance",
            "holdings_summary": [
                {
                    "ticker": "AAPL", "name": "Apple", "quantity": "10",
                    "avg_cost": "150.00", "current_price": "180.00",
                    "currency": "USD", "price_return_pct": 20.0,
                    "fx_return_pct": 3.0, "total_return_pct": 23.6,
                    "price_fetch_failed": False,
                },
                {
                    "ticker": "MSFT", "name": "Microsoft", "quantity": "5",
                    "avg_cost": "250.00", "current_price": "300.00",
                    "currency": "USD", "price_return_pct": 20.0,
                    "fx_return_pct": 3.0, "total_return_pct": 23.6,
                    "price_fetch_failed": False,
                },
            ],
            "optimization_result": None,
        }

        async def _run():
            with patch(
                "app.services.ml.optimizer.fetch_historical_prices",
                new_callable=AsyncMock,
                return_value=mock_df,
            ):
                return await _run_ml_optimization_safe(context_dict)

        result = asyncio.run(_run())
        assert result is not None
        assert result["status"] == "success"
        assert "summary" in result

    def test_ml_optimization_safe_returns_none_for_single_holding(self):
        """보유 종목이 1개이면 None을 반환해야 함 (분산 불가)"""
        from app.worker.tasks.ai_report_tasks import _run_ml_optimization_safe

        context_dict = {
            "usd_krw_rate": "1380",
            "holdings_summary": [
                {
                    "ticker": "AAPL", "quantity": "10",
                    "current_price": "180.00", "currency": "USD",
                    "price_fetch_failed": False,
                }
            ],
        }

        result = asyncio.run(_run_ml_optimization_safe(context_dict))
        assert result is None

    def test_ml_optimization_safe_returns_none_on_exception(self):
        """yfinance 오류 발생 시 None 반환 (전체 작업 중단하지 않음)"""
        from app.worker.tasks.ai_report_tasks import _run_ml_optimization_safe

        context_dict = {
            "usd_krw_rate": "1380",
            "holdings_summary": [
                {
                    "ticker": "AAPL", "quantity": "10",
                    "current_price": "180.00", "currency": "USD",
                    "price_fetch_failed": False,
                },
                {
                    "ticker": "MSFT", "quantity": "5",
                    "current_price": "300.00", "currency": "USD",
                    "price_fetch_failed": False,
                },
            ],
        }

        async def _run():
            with patch(
                "app.services.ml.optimizer.fetch_historical_prices",
                new_callable=AsyncMock,
                side_effect=Exception("yfinance network error"),
            ):
                return await _run_ml_optimization_safe(context_dict)

        result = asyncio.run(_run())
        assert result is None  # 실패해도 None 반환, 예외 전파 안 함


# ─────────────────────────────────────────────────────────────────────────────
# 내부 테스트 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

async def _run_optimization_with_mock_prices(
    tickers: list[str],
    current_weights: dict[str, float],
    mock_df: pd.DataFrame,
) -> dict:
    """fetch_historical_prices를 mock해서 run_portfolio_optimization 실행."""
    from app.services.ml.optimizer import run_portfolio_optimization

    with patch(
        "app.services.ml.optimizer.fetch_historical_prices",
        new_callable=AsyncMock,
        return_value=mock_df,
    ):
        return await run_portfolio_optimization(tickers, current_weights)
