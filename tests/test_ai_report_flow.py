"""
AI 리포트 비동기 흐름 단위 테스트

테스트 범위:
1. 프롬프트 빌더 — 3-layer 구조 및 캐싱 Prefix 검증
2. Celery 직렬화 — PortfolioContext Decimal 직렬화/역직렬화
3. 작업 상태 조회 — result_store 상태 파싱
4. 라우터 스키마 — 요청/응답 검증

실제 Gemini API / Redis 호출은 mock 처리 (유닛 테스트)
"""

import uuid
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.services.ai.prompt_builder import (
    INVESTMENT_ADVISOR_PERSONA,
    PortfolioContext,
    build_document_summary_prompt,
    build_portfolio_report_prompt,
)
from app.schemas.ai_report import (
    DocumentSummaryRequest,
    PortfolioReportRequest,
    TaskAcceptedResponse,
    TaskStatusResponse,
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. 프롬프트 빌더 테스트
# ─────────────────────────────────────────────────────────────────────────────

def _make_context(**kwargs) -> PortfolioContext:
    defaults = dict(
        portfolio_name="테스트 포트폴리오",
        total_cost_krw=Decimal("10000000"),
        total_value_krw=Decimal("11500000"),
        total_return_pct=Decimal("15.00"),
        price_contribution_krw=Decimal("1200000"),
        fx_contribution_krw=Decimal("300000"),
        usd_krw_rate=Decimal("1380"),
        rate_source="yfinance",
        holdings_summary=[],
        optimization_result=None,
    )
    defaults.update(kwargs)
    return PortfolioContext(**defaults)


class TestPromptBuilder:

    def test_three_layer_structure(self):
        """messages 배열이 반드시 3개 요소를 가져야 함"""
        ctx = _make_context()
        msgs = build_portfolio_report_prompt(ctx, "분석해주세요", "2026-05-27")
        assert len(msgs) == 3

    def test_persona_is_first_prefix(self):
        """PERSONA가 messages[0](user)의 parts에 고정되어야 함"""
        ctx = _make_context()
        msgs = build_portfolio_report_prompt(ctx, "질문", "2026-05-27")
        assert msgs[0]["role"] == "user"
        assert INVESTMENT_ADVISOR_PERSONA in msgs[0]["parts"][0]

    def test_cache_anchor_is_second(self):
        """messages[1]은 모델의 캐시 앵커 응답이어야 함"""
        ctx = _make_context()
        msgs = build_portfolio_report_prompt(ctx, "질문", "2026-05-27")
        assert msgs[1]["role"] == "model"
        assert "ARIA" in msgs[1]["parts"][0]

    def test_variable_data_is_last(self):
        """포트폴리오 데이터와 질문은 messages[2](마지막)에 있어야 함"""
        ctx = _make_context()
        question = "환차익을 분석해 주세요"
        msgs = build_portfolio_report_prompt(ctx, question, "2026-05-27")
        assert msgs[2]["role"] == "user"
        assert question in msgs[2]["parts"][0]
        assert "포트폴리오" in msgs[2]["parts"][0]

    def test_persona_not_in_last_message(self):
        """가변 데이터(messages[2])에 PERSONA 전체가 중복되지 않아야 함"""
        ctx = _make_context()
        msgs = build_portfolio_report_prompt(ctx, "질문", "2026-05-27")
        # messages[2]는 포트폴리오 데이터만 포함, PERSONA 원문 전체 중복 없어야 함
        assert INVESTMENT_ADVISOR_PERSONA not in msgs[2]["parts"][0]

    def test_implicit_cache_token_threshold(self):
        """고정 Prefix가 암시적 캐싱 1024 토큰 기준을 충족해야 함"""
        from app.services.ai.prompt_builder import MARKET_CONTEXT_TEMPLATE
        market_ctx = MARKET_CONTEXT_TEMPLATE.format(
            usd_krw=1380, rate_source="yfinance", analysis_time="2026-05-27"
        )
        full_prefix = INVESTMENT_ADVISOR_PERSONA + "\n\n" + market_ctx
        # 한국어 2자/토큰, ASCII 4자/토큰 혼합 보수적 추정
        korean_chars = sum(1 for c in full_prefix if ord(c) > 127)
        ascii_chars = len(full_prefix) - korean_chars
        est_tokens = (korean_chars // 2) + (ascii_chars // 4)
        assert est_tokens >= 1024, (
            f"Prefix 추정 토큰({est_tokens})이 암시적 캐싱 기준(1024)에 미달. "
            "PERSONA 또는 MARKET_CONTEXT를 보강하세요."
        )

    def test_holdings_in_last_message(self):
        """보유 종목 정보가 messages[2]에 포함되어야 함"""
        ctx = _make_context(holdings_summary=[{
            "ticker": "AAPL", "name": "Apple", "quantity": Decimal("10"),
            "avg_cost": Decimal("150"), "current_price": Decimal("180"),
            "currency": "USD", "price_return_pct": 20.0,
            "fx_return_pct": 3.0, "total_return_pct": 23.6,
        }])
        msgs = build_portfolio_report_prompt(ctx, "분석", "2026-05-27")
        assert "AAPL" in msgs[2]["parts"][0]

    def test_document_summary_prompt_structure(self):
        """문서 요약 프롬프트도 3-layer 구조여야 함"""
        msgs = build_document_summary_prompt(
            document_text="분기 실적 발표 내용...",
            document_type="earnings_call",
            ticker="AAPL",
        )
        assert len(msgs) == 3
        assert msgs[0]["role"] == "user"
        assert INVESTMENT_ADVISOR_PERSONA in msgs[0]["parts"][0]


# ─────────────────────────────────────────────────────────────────────────────
# 2. Celery 직렬화 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestCelerySerializtion:

    def test_decimal_serialized_as_string(self):
        """Celery JSON 직렬화를 위해 Decimal 값이 str로 변환되어야 함"""
        from app.api.v1.routers.ai_report import _valuation_to_context_dict

        # PortfolioValuation mock
        holding_mock = MagicMock()
        holding_mock.ticker = "AAPL"
        holding_mock.name = "Apple"
        holding_mock.quantity = Decimal("10")
        holding_mock.avg_cost = Decimal("150.00")
        holding_mock.current_price = Decimal("180.00")
        holding_mock.currency_code.value = "USD"
        holding_mock.price_return_pct = Decimal("20.00")
        holding_mock.fx_return_pct = Decimal("3.00")
        holding_mock.total_return_pct = Decimal("23.60")
        holding_mock.price_fetch_failed = False

        valuation_mock = MagicMock()
        valuation_mock.portfolio_name = "테스트"
        valuation_mock.total_cost_krw = Decimal("1000000")
        valuation_mock.total_value_krw = Decimal("1150000")
        valuation_mock.total_return_pct = Decimal("15.00")
        valuation_mock.price_contribution_krw = Decimal("120000")
        valuation_mock.fx_contribution_krw = Decimal("30000")
        valuation_mock.current_usd_krw_rate = Decimal("1380")
        valuation_mock.rate_source = "yfinance"
        valuation_mock.holdings = [holding_mock]

        ctx_dict = _valuation_to_context_dict(valuation_mock)

        # 모든 Decimal 값이 str로 변환됨
        assert isinstance(ctx_dict["total_cost_krw"], str)
        assert isinstance(ctx_dict["total_value_krw"], str)
        assert isinstance(ctx_dict["usd_krw_rate"], str)
        # 수치 정확성
        assert ctx_dict["total_cost_krw"] == "1000000"
        assert ctx_dict["holdings_summary"][0]["ticker"] == "AAPL"

    def test_context_dict_json_serializable(self):
        """딕셔너리가 JSON으로 직렬화 가능해야 함"""
        import json
        from app.api.v1.routers.ai_report import _valuation_to_context_dict

        holding_mock = MagicMock()
        holding_mock.ticker = "005930"
        holding_mock.name = "삼성전자"
        holding_mock.quantity = Decimal("100")
        holding_mock.avg_cost = Decimal("72000")
        holding_mock.current_price = Decimal("75000")
        holding_mock.currency_code.value = "KRW"
        holding_mock.price_return_pct = Decimal("4.17")
        holding_mock.fx_return_pct = Decimal("0.00")
        holding_mock.total_return_pct = Decimal("4.17")
        holding_mock.price_fetch_failed = False

        valuation_mock = MagicMock()
        valuation_mock.portfolio_name = "국내 포트폴리오"
        valuation_mock.total_cost_krw = Decimal("7200000")
        valuation_mock.total_value_krw = Decimal("7500000")
        valuation_mock.total_return_pct = Decimal("4.17")
        valuation_mock.price_contribution_krw = Decimal("300000")
        valuation_mock.fx_contribution_krw = Decimal("0")
        valuation_mock.current_usd_krw_rate = Decimal("1380")
        valuation_mock.rate_source = "cache"
        valuation_mock.holdings = [holding_mock]

        ctx_dict = _valuation_to_context_dict(valuation_mock)
        # JSON 직렬화 가능 여부 확인 (Decimal이 남아있으면 TypeError)
        serialized = json.dumps(ctx_dict)
        assert isinstance(serialized, str)


# ─────────────────────────────────────────────────────────────────────────────
# 3. 작업 상태 응답 스키마 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestTaskStatusSchema:

    def test_pending_status(self):
        resp = TaskStatusResponse(task_id="abc-123", status="PENDING")
        assert resp.status == "PENDING"
        assert resp.result is None
        assert resp.error is None

    def test_success_status_with_result(self):
        resp = TaskStatusResponse(
            task_id="abc-123",
            status="SUCCESS",
            result={"report": "포트폴리오 분석 완료", "usage": {"total_tokens": 1500}},
        )
        assert resp.status == "SUCCESS"
        assert resp.result["report"] == "포트폴리오 분석 완료"

    def test_failure_status_with_error(self):
        resp = TaskStatusResponse(
            task_id="abc-123",
            status="FAILURE",
            error="Gemini API rate limit exceeded",
        )
        assert resp.status == "FAILURE"
        assert "rate limit" in resp.error

    def test_task_accepted_response(self):
        resp = TaskAcceptedResponse(
            task_id="task-xyz",
            poll_url="/api/v1/ai/reports/tasks/task-xyz",
        )
        assert resp.status == "PENDING"
        assert resp.task_id == "task-xyz"


# ─────────────────────────────────────────────────────────────────────────────
# 4. 요청 스키마 검증
# ─────────────────────────────────────────────────────────────────────────────

class TestRequestSchemas:

    def test_portfolio_report_default_question(self):
        req = PortfolioReportRequest()
        assert len(req.question) >= 5

    def test_portfolio_report_custom_question(self):
        req = PortfolioReportRequest(question="환차익을 분석해 주세요.")
        assert req.question == "환차익을 분석해 주세요."

    def test_document_summary_minimum_text(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            DocumentSummaryRequest(document_text="짧음")  # 100자 미만

    def test_document_summary_valid(self):
        req = DocumentSummaryRequest(
            document_text="A" * 200,
            document_type="earnings_call",
            ticker="AAPL",
        )
        assert req.document_type == "earnings_call"
        assert req.ticker == "AAPL"
