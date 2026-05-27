"""
Celery 작업 결과 조회 헬퍼

FastAPI 라우터에서 task_id로 작업 상태와 결과를 조회할 때 사용.

상태 흐름:
  PENDING → STARTED → SUCCESS | FAILURE | RETRY
"""

from enum import Enum
from typing import Any

from celery.result import AsyncResult

from app.worker.celery_app import celery_app


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    STARTED = "STARTED"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    RETRY = "RETRY"
    REVOKED = "REVOKED"


def get_task_result(task_id: str) -> dict[str, Any]:
    """
    task_id로 Celery 작업 상태와 결과를 조회.

    반환 구조:
    {
        "task_id": str,
        "status": TaskStatus,
        "result": Any | None,   # SUCCESS 시 리포트 내용
        "error": str | None,    # FAILURE 시 오류 메시지
        "progress": int | None  # STARTED 시 진행률 (0-100)
    }
    """
    result = AsyncResult(task_id, app=celery_app)

    payload: dict[str, Any] = {
        "task_id": task_id,
        "status": result.state,
        "result": None,
        "error": None,
        "progress": None,
    }

    if result.state == "SUCCESS":
        payload["result"] = result.result
    elif result.state == "FAILURE":
        payload["error"] = str(result.result)
    elif result.state == "STARTED":
        meta = result.info or {}
        payload["progress"] = meta.get("progress", 0)

    return payload


def revoke_task(task_id: str, terminate: bool = False) -> bool:
    """진행 중인 작업 취소. terminate=True 시 강제 종료."""
    try:
        celery_app.control.revoke(task_id, terminate=terminate, signal="SIGTERM")
        return True
    except Exception:
        return False
