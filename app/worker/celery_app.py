"""
Celery 애플리케이션 팩토리

아키텍처 근거 (architecture_plan.md §4.1):
  LLM 총 응답 지연 = 서버 대기 + TTFT + (생성속도 × 출력토큰)
  10만 토큰 → 최대 8초, 50만 토큰 → 최대 24초
  → FastAPI 메인 루프에서 직접 대기 시 전체 서버 병목 발생
  → Celery 워커로 오프로딩, FastAPI는 즉시 task_id만 반환

큐 설계:
  ai_reports  — Gemini 리포트 생성 (높은 지연, 낮은 우선순위)
  market_data — 시세 갱신 (짧은 지연, 높은 우선순위)
  default     — 일반 백그라운드 작업

실행 커맨드:
  celery -A app.worker.celery_app worker --loglevel=info -Q ai_reports,market_data,celery
  celery -A app.worker.celery_app flower --port=5555   # 모니터링
"""

from celery import Celery
from kombu import Exchange, Queue

from app.core.config import settings

# ── Celery 앱 생성 ──────────────────────────────────────────────────────────
celery_app = Celery(
    "investment_platform",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.worker.tasks.ai_report_tasks",
    ],
)

# ── 큐 토폴로지 ─────────────────────────────────────────────────────────────
default_exchange = Exchange("default", type="direct")
ai_exchange = Exchange("ai", type="direct")
market_exchange = Exchange("market", type="direct")

celery_app.conf.task_queues = (
    Queue("default", default_exchange, routing_key="default"),
    Queue(
        "ai_reports",
        ai_exchange,
        routing_key="ai_reports",
        queue_arguments={"x-max-priority": 5},
    ),
    Queue(
        "market_data",
        market_exchange,
        routing_key="market_data",
        queue_arguments={"x-max-priority": 10},
    ),
)
celery_app.conf.task_default_queue = "default"
celery_app.conf.task_default_exchange = "default"
celery_app.conf.task_default_routing_key = "default"

# ── 라우팅 규칙 ─────────────────────────────────────────────────────────────
celery_app.conf.task_routes = {
    "app.worker.tasks.ai_report_tasks.*": {
        "queue": "ai_reports",
        "routing_key": "ai_reports",
    },
}

# ── Celery 설정 ─────────────────────────────────────────────────────────────
celery_app.conf.update(
    # 직렬화
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # 타임존
    timezone="Asia/Seoul",
    enable_utc=True,
    # 결과 보존 (24시간)
    result_expires=86400,
    # 워커 설정
    worker_prefetch_multiplier=1,   # LLM 작업은 오래 걸리므로 1개씩 처리
    task_acks_late=True,            # 완료 후 ack → 재시도 안전성 확보
    task_reject_on_worker_lost=True,
    # 재시도 정책
    task_max_retries=3,
    task_default_retry_delay=60,    # 1분 후 재시도
    # AI 리포트 타임아웃: LLM 응답 최대 2분
    task_soft_time_limit=120,
    task_time_limit=150,
)
