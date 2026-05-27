"""
대안 데이터(Alternative Data) Redis 캐시

SEC EDGAR / DART 데이터를 Redis에 캐싱하여:
  - 사용자 요청마다 외부 API를 실시간 호출하지 않음 (응답 지연 방지)
  - Celery Beat 백그라운드 스케줄러가 주기적으로 갱신
  - AI 리포트 Celery 태스크에서 즉시 조회 가능

키 구조:
  alt_data:sec:{TICKER_UPPER}    → JSON, TTL 21600s (6h)
  alt_data:dart:{TICKER_UPPER}   → JSON, TTL 86400s (24h)
  alt_data:watched:sec           → Redis Set, 최근 요청된 US 티커 추적
  alt_data:watched:dart          → Redis Set, 최근 요청된 KR 티커 추적
"""

import json
import logging
from typing import Any

import redis

from app.core.config import settings

logger = logging.getLogger(__name__)

# TTL 상수
SEC_CACHE_TTL = 21_600     # 6시간 — Form 4는 수시 공시, 6h 내 갱신
DART_CACHE_TTL = 86_400    # 24시간 — 재무제표는 분기별 변경
WATCHED_TTL = 604_800      # 7일 — 티커 추적 집합 만료


class AlternativeDataCache:
    """
    Redis 기반 대안 데이터 캐시.
    연결 실패 시 모든 메서드가 조용히 실패(fallback=None/[]).
    """

    def __init__(self) -> None:
        try:
            self._redis = redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
        except Exception:
            self._redis = None
            logger.warning("AlternativeDataCache: Redis 연결 실패 — 캐시 비활성화")

    # ── SEC EDGAR 캐시 ────────────────────────────────────────────────────────

    def set_sec_data(self, ticker: str, data: dict[str, Any]) -> None:
        self._set(f"alt_data:sec:{ticker.upper()}", data, SEC_CACHE_TTL)

    def get_sec_data(self, ticker: str) -> dict[str, Any] | None:
        return self._get(f"alt_data:sec:{ticker.upper()}")

    # ── DART 재무 데이터 캐시 ─────────────────────────────────────────────────

    def set_dart_data(self, ticker: str, data: dict[str, Any]) -> None:
        self._set(f"alt_data:dart:{ticker.upper()}", data, DART_CACHE_TTL)

    def get_dart_data(self, ticker: str) -> dict[str, Any] | None:
        return self._get(f"alt_data:dart:{ticker.upper()}")

    # ── 티커 추적 (Celery Beat 갱신 대상 관리) ───────────────────────────────

    def track_ticker(self, ticker: str, market: str) -> None:
        """
        최근 리포트 요청이 있었던 티커를 Redis Set에 등록.
        Celery Beat 주기 작업이 이 Set을 읽어 데이터를 갱신.

        Args:
            ticker: 종목 티커 (예: "AAPL", "005930")
            market: "sec" (US 주식) | "dart" (KR 주식)
        """
        try:
            if self._redis:
                key = f"alt_data:watched:{market}"
                self._redis.sadd(key, ticker.upper())
                self._redis.expire(key, WATCHED_TTL)
        except Exception as exc:
            logger.debug("track_ticker failed: %s", exc)

    def get_watched_tickers(self, market: str) -> list[str]:
        """Celery Beat 작업용 — 최근 요청된 티커 목록 반환."""
        try:
            if self._redis:
                return list(self._redis.smembers(f"alt_data:watched:{market}"))
        except Exception as exc:
            logger.debug("get_watched_tickers failed: %s", exc)
        return []

    # ── 내부 헬퍼 ─────────────────────────────────────────────────────────────

    def _set(self, key: str, value: dict, ttl: int) -> None:
        try:
            if self._redis:
                self._redis.setex(key, ttl, json.dumps(value, ensure_ascii=False))
        except Exception as exc:
            logger.debug("cache set failed key=%s: %s", key, exc)

    def _get(self, key: str) -> dict | None:
        try:
            if self._redis:
                raw = self._redis.get(key)
                if raw:
                    return json.loads(raw)
        except Exception as exc:
            logger.debug("cache get failed key=%s: %s", key, exc)
        return None


# 싱글턴 인스턴스
alt_data_cache = AlternativeDataCache()
