"""
AI 리포트 Celery 작업 (ai_reports 큐)

architecture_plan.md §4.1 + §5 구현:
  사용자 요청 → FastAPI 즉시 task_id 반환
  → Celery 워커(ai_reports 큐)가 백그라운드 처리
    ① ML 최적화 (PyPortfolioOpt) — Gemini 환각 방지 선행 연산 (§5)
    ② Gemini API 호출 — ML 결과를 컨텍스트로 주입 (§4.2 암시적 캐싱)
  → Redis에 결과 저장
  → 프론트엔드에서 폴링 또는 SSE로 결과 수신

작업 목록:
  generate_portfolio_report_task  — 포트폴리오 분석 리포트 (ML + 암시적 캐싱)
  generate_document_summary_task  — 어닝스 콜/공시 요약 (명시적 캐싱)

파이프라인 진행 단계:
  10%  context_loading   — Celery 직렬화 역직렬화
  25%  ml_optimization   — PyPortfolioOpt 최적화 (과거 데이터 수집 + 연산)
  50%  calling_gemini    — Gemini API 호출 (ML 결과 프롬프트 주입)
  90%  formatting        — 최종 결과 조립
"""

import asyncio
import uuid
from decimal import Decimal
from typing import Any

from celery import Task
from celery.utils.log import get_task_logger

from app.worker.celery_app import celery_app

logger = get_task_logger(__name__)


class _AIReportBaseTask(Task):
    """AI 리포트 작업 공통 기반 클래스."""
    abstract = True

    def on_failure(self, exc: Exception, task_id: str, args, kwargs, einfo) -> None:
        logger.error(
            "AI report task failed | task_id=%s error=%s",
            task_id,
            str(exc),
            exc_info=True,
        )

    def on_retry(self, exc: Exception, task_id: str, args, kwargs, einfo) -> None:
        logger.warning("Retrying AI report task | task_id=%s error=%s", task_id, exc)


# ─────────────────────────────────────────────────────────────────────────────
# Task 1: 포트폴리오 분석 리포트 (암시적 캐싱)
# ─────────────────────────────────────────────────────────────────────────────

@celery_app.task(
    bind=True,
    base=_AIReportBaseTask,
    name="app.worker.tasks.ai_report_tasks.generate_portfolio_report_task",
    queue="ai_reports",
    max_retries=3,
    default_retry_delay=60,
    soft_time_limit=200,   # ML 최적화(최대 30s) + Gemini(최대 24s) 여유분 포함
    time_limit=240,
)
def generate_portfolio_report_task(
    self: Task,
    portfolio_id: str,
    user_id: str,
    portfolio_context_dict: dict,
    user_question: str,
) -> dict[str, Any]:
    """
    포트폴리오 분석 리포트 Celery 태스크.

    처리 파이프라인 (architecture_plan.md §5):
      1. Decimal 역직렬화 → PortfolioContext 구성
      2. ML 최적화 (PyPortfolioOpt) — Gemini 환각 방지 선행 연산
      3. 최적화 결과를 PortfolioContext.optimization_result에 주입
      4. Gemini API 호출 → ML 수치 기반 자연어 리포트 생성

    Args:
        portfolio_id: 포트폴리오 UUID (로깅용)
        user_id: 사용자 UUID (로깅용)
        portfolio_context_dict: PortfolioContext 직렬화 딕셔너리 (Decimal → str)
        user_question: 사용자 질문

    Returns:
        Celery result backend에 저장될 리포트 딕셔너리
    """
    logger.info(
        "Starting portfolio report | task=%s portfolio=%s user=%s",
        self.request.id,
        portfolio_id,
        user_id,
    )

    # ── 1. Decimal 역직렬화 ─────────────────────────────────────────────
    self.update_state(state="STARTED", meta={"progress": 10, "step": "context_loading"})

    try:
        from app.services.ai.gemini_service import generate_portfolio_report
        from app.services.ai.prompt_builder import PortfolioContext

        ctx = PortfolioContext(
            portfolio_name=portfolio_context_dict["portfolio_name"],
            total_cost_krw=Decimal(str(portfolio_context_dict["total_cost_krw"])),
            total_value_krw=Decimal(str(portfolio_context_dict["total_value_krw"])),
            total_return_pct=Decimal(str(portfolio_context_dict["total_return_pct"])),
            price_contribution_krw=Decimal(str(portfolio_context_dict["price_contribution_krw"])),
            fx_contribution_krw=Decimal(str(portfolio_context_dict["fx_contribution_krw"])),
            usd_krw_rate=Decimal(str(portfolio_context_dict["usd_krw_rate"])),
            rate_source=portfolio_context_dict["rate_source"],
            holdings_summary=portfolio_context_dict["holdings_summary"],
            optimization_result=portfolio_context_dict.get("optimization_result"),
        )

        # ── 2. ML 최적화 — Gemini 호출 전 선행 수치 연산 ───────────────
        # architecture_plan.md §5: "AI 호출 이전에 ML 파이프라인을 선행 구동"
        self.update_state(state="STARTED", meta={"progress": 25, "step": "ml_optimization"})

        opt_result = asyncio.run(_run_ml_optimization_safe(portfolio_context_dict))
        if opt_result:
            ctx.optimization_result = opt_result
            logger.info(
                "ML optimization completed | task=%s status=%s tickers=%s",
                self.request.id,
                opt_result.get("status"),
                opt_result.get("tickers"),
            )
        else:
            logger.info("ML optimization skipped (insufficient data) | task=%s", self.request.id)

        # ── 3. Gemini API 호출 (ML 결과 컨텍스트 주입 완료 상태) ──────
        self.update_state(state="STARTED", meta={"progress": 50, "step": "calling_gemini"})

        result = asyncio.run(generate_portfolio_report(ctx, user_question))

        self.update_state(state="STARTED", meta={"progress": 90, "step": "formatting"})

        final_result = {
            "task_id": self.request.id,
            "portfolio_id": portfolio_id,
            "user_id": user_id,
            "question": user_question,
            "ml_optimization_status": opt_result.get("status") if opt_result else "skipped",
            **result,
        }

        logger.info(
            "Portfolio report completed | task=%s tokens=%s cached=%s ml=%s",
            self.request.id,
            result["usage"]["total_tokens"],
            result["usage"]["cached_tokens"],
            final_result["ml_optimization_status"],
        )
        return final_result

    except Exception as exc:
        logger.error("Portfolio report failed | task=%s error=%s", self.request.id, exc)
        raise self.retry(exc=exc, countdown=60)


# ── ML 최적화 헬퍼 ───────────────────────────────────────────────────────────

async def _run_ml_optimization_safe(context_dict: dict) -> dict | None:
    """
    ML 최적화 실행 헬퍼 — 실패해도 AI 리포트 생성은 계속 진행.

    architecture_plan.md §5.1:
      tickers → yfinance 과거 3년 데이터 → 공분산 행렬 → 4가지 최적화
      → optimization_result dict (summary 필드 포함)

    실패 조건 (None 반환):
      - 보유 종목이 1개 이하
      - 가격 조회 실패 종목만 있는 경우
      - yfinance 데이터 수집 오류
    """
    try:
        from app.services.ml.optimizer import run_portfolio_optimization

        holdings = context_dict.get("holdings_summary", [])
        # 가격 조회 실패 종목 제외
        valid_holdings = [h for h in holdings if not h.get("price_fetch_failed", False)]

        if len(valid_holdings) < 2:
            return None

        usd_krw = float(context_dict.get("usd_krw_rate", 1380))

        # KRW 기준 현재 시장가 비중 계산
        values: dict[str, float] = {}
        for h in valid_holdings:
            ticker = h["ticker"]
            qty = float(h["quantity"])
            price = float(h["current_price"])
            currency = h.get("currency", "USD")
            fx = usd_krw if currency != "KRW" else 1.0
            values[ticker] = qty * price * fx

        total_value = sum(values.values())
        if total_value <= 0:
            return None

        current_weights = {t: v / total_value for t, v in values.items()}
        tickers = list(values.keys())

        return await run_portfolio_optimization(tickers, current_weights)

    except Exception as exc:
        # ML 최적화 실패는 전체 작업을 중단시키지 않음
        logger.warning("ML optimization failed silently | error=%s", exc)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Task 2: 문서 요약 (명시적 캐싱 — 어닝스 콜, 공시 리포트)
# ─────────────────────────────────────────────────────────────────────────────

@celery_app.task(
    bind=True,
    base=_AIReportBaseTask,
    name="app.worker.tasks.ai_report_tasks.generate_document_summary_task",
    queue="ai_reports",
    max_retries=2,
    default_retry_delay=120,
    soft_time_limit=180,
    time_limit=210,
)
def generate_document_summary_task(
    self: Task,
    document_text: str,
    document_type: str,
    ticker: str | None,
    user_question: str,
    ttl_seconds: int | None,
    requested_by_user_id: str,
) -> dict[str, Any]:
    """
    초거대 문서 요약 태스크 (명시적 캐싱).

    다수 사용자가 동일 문서를 요청할 때:
      첫 번째 호출: 캐시 객체 생성 (느림)
      이후 호출:    캐시 히트 (빠름, 비용 90% 절감)
    """
    logger.info(
        "Starting document summary | task=%s type=%s ticker=%s",
        self.request.id,
        document_type,
        ticker,
    )

    self.update_state(state="STARTED", meta={"progress": 5, "step": "initializing"})

    try:
        from app.services.ai.gemini_service import generate_document_summary

        self.update_state(state="STARTED", meta={"progress": 20, "step": "cache_check"})

        result = asyncio.run(
            generate_document_summary(
                document_text=document_text,
                document_type=document_type,
                ticker=ticker,
                user_question=user_question,
                ttl_seconds=ttl_seconds,
            )
        )

        final_result = {
            "task_id": self.request.id,
            "document_type": document_type,
            "ticker": ticker,
            "requested_by": requested_by_user_id,
            **result,
        }

        logger.info(
            "Document summary completed | task=%s cache_hit=%s cached_tokens=%s",
            self.request.id,
            result["cache_hit"],
            result["usage"]["cached_tokens"],
        )
        return final_result

    except Exception as exc:
        logger.error("Document summary failed | task=%s error=%s", self.request.id, exc)
        raise self.retry(exc=exc, countdown=120)
