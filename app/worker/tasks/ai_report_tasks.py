"""
AI 리포트 Celery 작업 (ai_reports 큐)

architecture_plan.md §4.1 구현:
  사용자 요청 → FastAPI 즉시 task_id 반환
  → Celery 워커(ai_reports 큐)가 백그라운드 처리
  → Redis에 결과 저장
  → 프론트엔드에서 폴링 또는 SSE로 결과 수신

작업 목록:
  generate_portfolio_report_task  — 포트폴리오 분석 리포트 (암시적 캐싱)
  generate_document_summary_task  — 어닝스 콜/공시 요약 (명시적 캐싱)
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
    soft_time_limit=120,
    time_limit=150,
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

    Args:
        portfolio_id: 포트폴리오 UUID (로깅용)
        user_id: 사용자 UUID (로깅용)
        portfolio_context_dict: PortfolioContext 직렬화 딕셔너리
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

    # 진행 상태 업데이트 (클라이언트 폴링용)
    self.update_state(state="STARTED", meta={"progress": 10, "step": "context_loading"})

    try:
        from app.services.ai.gemini_service import generate_portfolio_report
        from app.services.ai.prompt_builder import PortfolioContext

        # Decimal 역직렬화 (JSON 전송 시 문자열로 변환됨)
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

        self.update_state(state="STARTED", meta={"progress": 30, "step": "calling_gemini"})

        # asyncio.run()으로 비동기 Gemini 호출 실행
        result = asyncio.run(generate_portfolio_report(ctx, user_question))

        self.update_state(state="STARTED", meta={"progress": 90, "step": "formatting"})

        final_result = {
            "task_id": self.request.id,
            "portfolio_id": portfolio_id,
            "user_id": user_id,
            "question": user_question,
            **result,
        }

        logger.info(
            "Portfolio report completed | task=%s tokens=%s cached=%s",
            self.request.id,
            result["usage"]["total_tokens"],
            result["usage"]["cached_tokens"],
        )
        return final_result

    except Exception as exc:
        logger.error("Portfolio report failed | task=%s error=%s", self.request.id, exc)
        raise self.retry(exc=exc, countdown=60)


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
