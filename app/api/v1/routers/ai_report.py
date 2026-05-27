"""
AI 리포트 비동기 라우터

이벤트 주도(Event-Driven) 설계 (architecture_plan.md §4.1):
─────────────────────────────────────────────────────────────────────
  사용자 요청
    ↓ POST /ai/reports/portfolio/{id}
  FastAPI (즉시 202 + task_id 반환)
    ↓ .delay()
  Celery ai_reports 큐
    ↓ 백그라운드 Gemini API 호출 (최대 120초)
  Redis result backend
    ↑ GET /ai/reports/tasks/{task_id}
  클라이언트 폴링 → 완료 시 리포트 수신
─────────────────────────────────────────────────────────────────────

엔드포인트:
  POST /api/v1/ai/reports/portfolio/{portfolio_id}
    → 포트폴리오 분석 리포트 요청 (암시적 캐싱)
  POST /api/v1/ai/reports/documents
    → 어닝스 콜/공시 문서 요약 요청 (명시적 캐싱)
  GET  /api/v1/ai/reports/tasks/{task_id}
    → 작업 상태/결과 폴링
  DELETE /api/v1/ai/reports/tasks/{task_id}
    → 진행 중 작업 취소

핵심 제약: 실제 매매 없음 — 분석 리포트 생성 전용
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.market_data.exchange_rate_adapter import ExchangeRateAdapter
from app.adapters.market_data.factory import get_exchange_rate_adapter
from app.auth.dependencies import get_current_active_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.ai_report import (
    DocumentSummaryRequest,
    PortfolioReportRequest,
    TaskAcceptedResponse,
    TaskStatusResponse,
)
from app.services.portfolio_service import _get_portfolio_or_404
from app.services.valuation_service import evaluate_portfolio
from app.worker.result_store import TaskStatus, get_task_result, revoke_task
from app.worker.tasks.ai_report_tasks import (
    generate_document_summary_task,
    generate_portfolio_report_task,
)

router = APIRouter(prefix="/ai/reports", tags=["AI Reports"])


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _poll_url(request: Request, task_id: str) -> str:
    return str(request.url_for("get_task_status", task_id=task_id))


def _valuation_to_context_dict(valuation) -> dict:
    """
    PortfolioValuation → Celery 직렬화 가능한 딕셔너리 변환.
    Decimal → str 변환 (JSON 직렬화 호환).
    """
    holdings_summary = [
        {
            "ticker": h.ticker,
            "name": h.name,
            "quantity": str(h.quantity),
            "avg_cost": str(h.avg_cost),
            "current_price": str(h.current_price),
            "currency": h.currency_code.value,
            "price_return_pct": float(h.price_return_pct),
            "fx_return_pct": float(h.fx_return_pct),
            "total_return_pct": float(h.total_return_pct),
            "price_fetch_failed": h.price_fetch_failed,
        }
        for h in valuation.holdings
    ]
    return {
        "portfolio_name": valuation.portfolio_name,
        "total_cost_krw": str(valuation.total_cost_krw),
        "total_value_krw": str(valuation.total_value_krw),
        "total_return_pct": str(valuation.total_return_pct),
        "price_contribution_krw": str(valuation.price_contribution_krw),
        "fx_contribution_krw": str(valuation.fx_contribution_krw),
        "usd_krw_rate": str(valuation.current_usd_krw_rate),
        "rate_source": valuation.rate_source,
        "holdings_summary": holdings_summary,
        "optimization_result": None,
    }


# ── 포트폴리오 리포트 요청 ────────────────────────────────────────────────────

@router.post(
    "/portfolio/{portfolio_id}",
    response_model=TaskAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="포트폴리오 AI 분석 리포트 요청",
    description=(
        "Celery 큐에 AI 리포트 작업을 등록하고 즉시 task_id를 반환합니다. "
        "실제 리포트는 백그라운드에서 생성되며, poll_url로 결과를 폴링하세요. "
        "암시적 캐싱으로 반복 요청 비용이 자동 절감됩니다."
    ),
)
async def request_portfolio_report(
    portfolio_id: uuid.UUID,
    req: PortfolioReportRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    fx_adapter: Annotated[ExchangeRateAdapter, Depends(get_exchange_rate_adapter)],
) -> TaskAcceptedResponse:
    # 1. 포트폴리오 소유권 확인 + 실시간 가치 평가
    portfolio = await _get_portfolio_or_404(db, portfolio_id, current_user)
    valuation = await evaluate_portfolio(db, portfolio, fx_adapter)

    # 2. Celery 직렬화용 딕셔너리 변환
    context_dict = _valuation_to_context_dict(valuation)

    # 3. Celery ai_reports 큐에 작업 등록 (즉시 반환)
    task = generate_portfolio_report_task.delay(
        portfolio_id=str(portfolio_id),
        user_id=str(current_user.id),
        portfolio_context_dict=context_dict,
        user_question=req.question,
    )

    return TaskAcceptedResponse(
        task_id=task.id,
        message=f"'{portfolio.name}' 포트폴리오 AI 분석 작업이 등록되었습니다.",
        poll_url=_poll_url(request, task.id),
    )


# ── 문서 요약 요청 ────────────────────────────────────────────────────────────

@router.post(
    "/documents",
    response_model=TaskAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="어닝스 콜 / 공시 문서 AI 요약 요청",
    description=(
        "초거대 문서(어닝스 콜 대본, 증권사 리포트, DART 공시)를 Gemini로 요약합니다. "
        "8000 토큰 이상 문서: 명시적 캐싱(TTL 캐시 객체) 자동 적용 → 96% 비용 절감. "
        "미만 문서: 암시적 캐싱 처리."
    ),
)
async def request_document_summary(
    req: DocumentSummaryRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> TaskAcceptedResponse:
    task = generate_document_summary_task.delay(
        document_text=req.document_text,
        document_type=req.document_type,
        ticker=req.ticker,
        user_question=req.user_question,
        ttl_seconds=req.ttl_seconds,
        requested_by_user_id=str(current_user.id),
    )

    doc_label = f"{req.document_type}" + (f" ({req.ticker})" if req.ticker else "")
    return TaskAcceptedResponse(
        task_id=task.id,
        message=f"'{doc_label}' 문서 요약 작업이 등록되었습니다.",
        poll_url=_poll_url(request, task.id),
    )


# ── 작업 상태 폴링 ────────────────────────────────────────────────────────────

@router.get(
    "/tasks/{task_id}",
    response_model=TaskStatusResponse,
    name="get_task_status",
    summary="AI 리포트 작업 상태 조회",
    description=(
        "task_id로 Celery 작업 상태를 조회합니다.\n\n"
        "**상태 흐름:** PENDING → STARTED (progress 0~100) → SUCCESS | FAILURE\n\n"
        "**폴링 권장 간격:** PENDING/STARTED 시 3~5초 간격으로 재요청"
    ),
)
async def get_task_status(
    task_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> TaskStatusResponse:
    result = get_task_result(task_id)
    return TaskStatusResponse(
        task_id=result["task_id"],
        status=result["status"],
        progress=result.get("progress"),
        result=result.get("result"),
        error=result.get("error"),
    )


# ── 작업 취소 ─────────────────────────────────────────────────────────────────

@router.delete(
    "/tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="AI 리포트 작업 취소",
)
async def cancel_task(
    task_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> None:
    success = revoke_task(task_id, terminate=True)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found or already completed",
        )
