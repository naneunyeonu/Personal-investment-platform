"""
AI 리포트 요청/응답 스키마

비동기 흐름:
  POST /ai/reports/portfolio/{id}  → 202 Accepted + task_id 즉시 반환
  GET  /ai/reports/tasks/{task_id} → 작업 상태/결과 폴링
  POST /ai/reports/documents       → 202 Accepted + task_id (문서 요약)
"""

from enum import Enum

from pydantic import BaseModel, Field


# ── 요청 스키마 ───────────────────────────────────────────────────────────────

class PortfolioReportRequest(BaseModel):
    question: str = Field(
        default="현재 포트폴리오를 종합 분석하고 리스크 요인을 알려주세요.",
        min_length=5,
        max_length=500,
        description="AI 비서에게 전달할 분석 질문",
    )


class DocumentSummaryRequest(BaseModel):
    document_text: str = Field(
        min_length=100,
        description="요약할 문서 전문 (어닝스 콜 대본, 증권사 리포트 등)",
    )
    document_type: str = Field(
        default="earnings_call",
        description="문서 유형: earnings_call | analyst_report | dart_filing | macro_report",
    )
    ticker: str | None = Field(
        default=None,
        max_length=20,
        description="관련 종목 티커 (선택)",
    )
    user_question: str = Field(
        default="핵심 내용을 투자자 관점에서 요약해 주세요.",
        max_length=500,
    )
    ttl_seconds: int | None = Field(
        default=None,
        ge=300,
        le=86400,
        description="명시적 캐시 TTL (초). 미입력 시 settings.GEMINI_CACHE_TTL_SECONDS 사용",
    )


# ── 응답 스키마 ───────────────────────────────────────────────────────────────

class TaskAcceptedResponse(BaseModel):
    """202 Accepted — Celery 작업 접수 즉시 반환"""
    task_id: str
    status: str = "PENDING"
    message: str = "리포트 생성 작업이 큐에 등록되었습니다."
    poll_url: str = Field(description="결과 확인용 폴링 URL")


class TaskStatusResponse(BaseModel):
    """작업 상태 폴링 응답"""
    task_id: str
    status: str          # PENDING | STARTED | SUCCESS | FAILURE | RETRY
    progress: int | None = None   # 0~100 (STARTED 시)
    result: dict | None = None    # SUCCESS 시 리포트 내용
    error: str | None = None      # FAILURE 시 오류 메시지
