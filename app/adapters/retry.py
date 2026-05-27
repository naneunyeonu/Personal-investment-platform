"""
외부 API 호출 재시도(Retry) 유틸리티

일시적 네트워크 오류(연결 실패, 타임아웃) 또는 Rate Limit(HTTP 429),
서버 일시 오류(HTTP 5xx)에 대해 지수 백오프(Exponential Backoff)로 재시도.

사용 예:
    # 비동기 함수 재시도
    result = await async_retry(my_coro_fn, arg1, arg2, max_attempts=3)

    # 동기 함수 재시도 (asyncio.to_thread 내부 blocking 함수에서)
    result = sync_retry(blocking_fn, arg1, arg2, max_attempts=3)

설계 원칙:
  - httpx 일시적 오류 + HTTP 429/5xx → 재시도
  - 그 외 예외(데이터 오류, 인증 오류 등) → 즉시 전파
  - AdapterError는 재시도 없이 즉시 전파 (데이터 없음 등 확정적 실패)
  - 최대 3회 / base_delay=1s / backoff=2.0 (→ 1s, 2s 대기)
"""

import asyncio
import logging
import time
from typing import Any, Callable

import httpx

logger = logging.getLogger(__name__)

# ── 재시도 대상 httpx 예외 ─────────────────────────────────────────────────
_HTTPX_TRANSIENT: tuple[type[Exception], ...] = (
    httpx.ConnectError,        # DNS 실패 / 연결 거부
    httpx.TimeoutException,    # 연결 타임아웃 / 읽기 타임아웃
    httpx.RemoteProtocolError, # 서버 비정상 응답 프로토콜
    httpx.ReadError,           # 읽기 중 연결 끊김
    httpx.WriteError,          # 쓰기 중 연결 끊김
    httpx.PoolTimeout,         # 커넥션 풀 대기 초과
)


def _is_retryable_status(status_code: int) -> bool:
    """HTTP 429 (Rate Limit) 또는 5xx (서버 일시 오류) → 재시도 대상."""
    return status_code == 429 or status_code >= 500


async def async_retry(
    coro_fn: Callable[..., Any],
    *args: Any,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    backoff_factor: float = 2.0,
    **kwargs: Any,
) -> Any:
    """
    비동기 코루틴 함수를 지수 백오프로 최대 max_attempts 번 재시도.

    Args:
        coro_fn:        재시도할 코루틴 함수 (coroutine function)
        *args:          coro_fn 위치 인수
        max_attempts:   최대 시도 횟수 (기본 3)
        base_delay:     첫 재시도 대기 시간 초 (기본 1.0)
        backoff_factor: 지수 배수 (기본 2.0 → 1s → 2s)
        **kwargs:       coro_fn 키워드 인수

    대기 패턴: attempt 1→2 : base_delay, attempt 2→3 : base_delay × backoff_factor
    예: base_delay=1, backoff_factor=2 → 1s → 2s

    Raises:
        마지막 시도에서 발생한 예외
    """
    last_exc: BaseException | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return await coro_fn(*args, **kwargs)
        except _HTTPX_TRANSIENT as exc:
            last_exc = exc
        except httpx.HTTPStatusError as exc:
            if not _is_retryable_status(exc.response.status_code):
                raise
            last_exc = exc
        # 그 외 예외(AdapterError, ValueError 등) → 즉시 전파

        if attempt < max_attempts:
            delay = base_delay * (backoff_factor ** (attempt - 1))
            logger.debug(
                "외부 API 재시도 %d/%d — %.1f초 대기 | 원인: %s(%s)",
                attempt, max_attempts, delay,
                type(last_exc).__name__, str(last_exc)[:80],
            )
            await asyncio.sleep(delay)

    assert last_exc is not None
    raise last_exc


def sync_retry(
    fn: Callable[..., Any],
    *args: Any,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    backoff_factor: float = 2.0,
    **kwargs: Any,
) -> Any:
    """
    동기 함수를 지수 백오프로 최대 max_attempts 번 재시도.

    asyncio.to_thread() 내부에서 실행되는 blocking 함수(yfinance, KIS httpx.Client 등)
    에서 사용. 함수 시그니처는 async_retry와 동일.

    Raises:
        마지막 시도에서 발생한 예외
    """
    last_exc: BaseException | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return fn(*args, **kwargs)
        except _HTTPX_TRANSIENT as exc:
            last_exc = exc
        except httpx.HTTPStatusError as exc:
            if not _is_retryable_status(exc.response.status_code):
                raise
            last_exc = exc
        # 그 외 예외 → 즉시 전파

        if attempt < max_attempts:
            delay = base_delay * (backoff_factor ** (attempt - 1))
            logger.debug(
                "외부 API 재시도 %d/%d — %.1f초 대기 | 원인: %s(%s)",
                attempt, max_attempts, delay,
                type(last_exc).__name__, str(last_exc)[:80],
            )
            time.sleep(delay)

    assert last_exc is not None
    raise last_exc
