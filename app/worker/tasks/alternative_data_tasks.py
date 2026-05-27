"""
대안 데이터(Alternative Data) 수집 Celery 태스크

architecture_plan.md §6: "내부자 거래 추적 + DART 재무공시 파싱"

사용자 요청마다 외부 API를 실시간 호출하면 리포트 생성이 느려지므로:
  → Celery Beat 주기적 갱신으로 Redis에 캐싱
  → AI 리포트 태스크는 캐시에서 즉시 조회

스케줄 (celery_app.py beat_schedule):
  alt_data.refresh_sec_insider  — 6시간마다: Form 4 공시 갱신
  alt_data.refresh_dart_financials — 매일 02:00: 재무제표 갱신

수동 실행:
  celery -A app.worker.celery_app call alt_data.refresh_sec_insider
  celery -A app.worker.celery_app call alt_data.refresh_dart_financials
"""

import asyncio
import logging
from typing import Any

from celery import Task
from celery.utils.log import get_task_logger

from app.worker.celery_app import celery_app

logger = get_task_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Task 1: SEC EDGAR 내부자 거래 갱신 (6시간 주기)
# ─────────────────────────────────────────────────────────────────────────────

@celery_app.task(
    name="alt_data.refresh_sec_insider",
    queue="alternative_data",
    max_retries=2,
    default_retry_delay=300,
    soft_time_limit=120,
    time_limit=150,
    ignore_result=True,
)
def refresh_sec_insider_data_task() -> None:
    """
    최근 AI 리포트 요청이 있었던 US 티커에 대해
    SEC EDGAR Form 4 내부자 거래 데이터를 갱신하고 Redis에 캐싱.

    갱신 대상: alt_data:watched:sec Redis Set에 등록된 티커
    """
    from app.adapters.alternative_data.redis_cache import alt_data_cache

    tickers = alt_data_cache.get_watched_tickers("sec")
    if not tickers:
        logger.info("SEC refresh: 갱신 대상 티커 없음 (watched set 비어있음)")
        return

    logger.info("SEC refresh 시작 | 대상 티커: %s", tickers)
    results = asyncio.run(_refresh_sec_for_tickers(tickers))
    success = sum(1 for r in results if r)
    logger.info("SEC refresh 완료 | 성공: %d/%d", success, len(tickers))


async def _refresh_sec_for_tickers(tickers: list[str]) -> list[bool]:
    """비동기 병렬로 여러 티커의 SEC 데이터 갱신."""
    from app.adapters.alternative_data.redis_cache import alt_data_cache
    from app.adapters.alternative_data.sec_edgar_adapter import SecEdgarAdapter

    adapter = SecEdgarAdapter()

    async def _refresh_one(ticker: str) -> bool:
        try:
            data = await adapter.get_insider_transactions(ticker)
            alt_data_cache.set_sec_data(ticker, data)
            logger.debug("SEC 갱신 완료: %s signal=%s", ticker, data.get("signal"))
            return True
        except Exception as exc:
            logger.warning("SEC 갱신 실패: ticker=%s error=%s", ticker, exc)
            return False

    import asyncio as _asyncio
    results = await _asyncio.gather(*[_refresh_one(t) for t in tickers])
    return list(results)


# ─────────────────────────────────────────────────────────────────────────────
# Task 2: DART 재무공시 갱신 (매일 02:00)
# ─────────────────────────────────────────────────────────────────────────────

@celery_app.task(
    name="alt_data.refresh_dart_financials",
    queue="alternative_data",
    max_retries=2,
    default_retry_delay=600,
    soft_time_limit=300,
    time_limit=360,
    ignore_result=True,
)
def refresh_dart_financial_data_task() -> None:
    """
    최근 AI 리포트 요청이 있었던 KR 티커에 대해
    DART 재무제표 데이터를 갱신하고 Redis에 캐싱.

    갱신 대상: alt_data:watched:dart Redis Set에 등록된 티커
    """
    from app.adapters.alternative_data.redis_cache import alt_data_cache

    tickers = alt_data_cache.get_watched_tickers("dart")
    if not tickers:
        logger.info("DART refresh: 갱신 대상 티커 없음")
        return

    logger.info("DART refresh 시작 | 대상 티커: %s", tickers)
    results = asyncio.run(_refresh_dart_for_tickers(tickers))
    success = sum(1 for r in results if r)
    logger.info("DART refresh 완료 | 성공: %d/%d", success, len(tickers))


async def _refresh_dart_for_tickers(tickers: list[str]) -> list[bool]:
    """순차 처리 (DART API rate limit 고려)."""
    from app.adapters.alternative_data.dart_adapter import DartAdapter
    from app.adapters.alternative_data.redis_cache import alt_data_cache

    adapter = DartAdapter()
    results = []

    for ticker in tickers:
        try:
            data = await adapter.get_financial_statements(ticker)
            alt_data_cache.set_dart_data(ticker, data)
            logger.debug(
                "DART 갱신 완료: %s corp=%s year=%s",
                ticker, data.get("corp_name"), data.get("bsns_year"),
            )
            results.append(True)
        except Exception as exc:
            logger.warning("DART 갱신 실패: ticker=%s error=%s", ticker, exc)
            results.append(False)

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Task 3: 온-디맨드 단일 티커 즉시 수집 (AI 리포트 캐시 미스 시)
# ─────────────────────────────────────────────────────────────────────────────

@celery_app.task(
    name="alt_data.fetch_for_ticker",
    queue="alternative_data",
    max_retries=1,
    soft_time_limit=30,
    time_limit=40,
    ignore_result=True,
)
def fetch_alternative_data_for_ticker_task(ticker: str, market: str) -> None:
    """
    단일 티커 즉시 수집 (캐시 미스 복구용).
    AI 리포트 태스크에서 캐시 미스 감지 시 비동기 트리거.

    Args:
        ticker: 종목 티커
        market: "sec" | "dart"
    """
    asyncio.run(_fetch_one_ticker(ticker, market))


async def _fetch_one_ticker(ticker: str, market: str) -> None:
    from app.adapters.alternative_data.redis_cache import alt_data_cache

    if market == "sec":
        from app.adapters.alternative_data.sec_edgar_adapter import SecEdgarAdapter
        adapter = SecEdgarAdapter()
        data = await adapter.get_insider_transactions(ticker)
        alt_data_cache.set_sec_data(ticker, data)
        alt_data_cache.track_ticker(ticker, "sec")
    elif market == "dart":
        from app.adapters.alternative_data.dart_adapter import DartAdapter
        adapter = DartAdapter()
        data = await adapter.get_financial_statements(ticker)
        alt_data_cache.set_dart_data(ticker, data)
        alt_data_cache.track_ticker(ticker, "dart")
