"""
Gemini API 서비스

architecture_plan.md §4.2 캐싱 전략 구현:
─────────────────────────────────────────────────────────────────────
암시적 캐싱 (Implicit Caching):
  - 모든 요청에서 INVESTMENT_ADVISOR_PERSONA를 messages[0]으로 고정
  - 1024+ 토큰 Prefix 유사도 자동 감지 → Gemini 자동 캐시 적용
  - 개인화 포트폴리오 분석, 대화 세션에 사용

명시적 캐싱 (Explicit Caching):
  - 어닝스 콜 대본, 증권사 리포트 등 초거대 문서
  - caching.CachedContent.create()로 TTL 지정 캐시 객체 생성
  - 생성된 cache_name을 GenerativeModel에 주입하여 재사용
─────────────────────────────────────────────────────────────────────

비용 비교 (architecture_plan.md §4.2 인용):
  캐싱 미적용: 100명 × 5만 토큰 × 15회/일 = $38/일
  캐싱 적용:   스토리지 포함 = $1.37/일 (96% 절감)
"""

import time
from datetime import datetime, timezone
from typing import Any

import google.generativeai as genai
from google.generativeai import caching as gemini_caching

from app.core.config import settings
from app.services.ai.prompt_builder import (
    PortfolioContext,
    build_document_summary_prompt,
    build_portfolio_report_prompt,
)

# ── SDK 초기화 ──────────────────────────────────────────────────────────────
genai.configure(api_key=settings.GEMINI_API_KEY)

# 명시적 캐시 인메모리 레지스트리: {cache_key → (cache_name, expires_at)}
_explicit_cache_registry: dict[str, tuple[str, float]] = {}


def _get_model(cache_name: str | None = None) -> genai.GenerativeModel:
    """
    Gemini 모델 인스턴스 반환.
    cache_name 지정 시 명시적 캐시 적용 모델 반환.
    """
    if cache_name:
        cached_content = gemini_caching.CachedContent(model=settings.GEMINI_MODEL, name=cache_name)
        return genai.GenerativeModel.from_cached_content(cached_content)
    return genai.GenerativeModel(model_name=settings.GEMINI_MODEL)


# ─────────────────────────────────────────────────────────────────────────────
# 1. 개인화 포트폴리오 리포트 — 암시적 캐싱
# ─────────────────────────────────────────────────────────────────────────────

async def generate_portfolio_report(
    context: PortfolioContext,
    user_question: str,
) -> dict[str, Any]:
    """
    포트폴리오 분석 리포트 생성 (암시적 캐싱 적용).

    프롬프트 구조:
      [고정 Prefix: PERSONA + 시장환경]  ← 캐시 히트 대상
      [모델 확인 응답]                   ← 캐시 앵커
      [가변: 포트폴리오 데이터 + 질문]   ← 사용자별 동적

    반환:
      {
        "report": str,           # 생성된 리포트 전문
        "usage": dict,           # 토큰 사용량
        "cached_tokens": int,    # 캐시 히트된 토큰 수
        "model": str,
        "generated_at": str,
      }
    """
    analysis_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    messages = build_portfolio_report_prompt(context, user_question, analysis_time)

    model = _get_model()

    # GenerativeModel.generate_content()는 동기 호출이므로 Celery 워커에서 실행
    response = model.generate_content(
        contents=messages,
        generation_config=genai.GenerationConfig(
            temperature=0.3,        # 금융 분석: 낮은 창의성, 높은 정확성
            max_output_tokens=2048,
            top_p=0.9,
        ),
    )

    usage = response.usage_metadata
    cached_tokens = getattr(usage, "cached_content_token_count", 0) or 0

    return {
        "report": response.text,
        "usage": {
            "prompt_tokens": usage.prompt_token_count,
            "output_tokens": usage.candidates_token_count,
            "cached_tokens": cached_tokens,
            "total_tokens": usage.total_token_count,
        },
        "cached_tokens": cached_tokens,
        "model": settings.GEMINI_MODEL,
        "generated_at": analysis_time,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 2. 초거대 문서 요약 — 명시적 캐싱 (Explicit Caching)
# ─────────────────────────────────────────────────────────────────────────────

def _get_or_create_explicit_cache(
    cache_key: str,
    document_text: str,
    document_type: str,
    ticker: str | None,
    ttl_seconds: int,
) -> str:
    """
    명시적 캐시 객체 조회 또는 생성.

    동일 cache_key가 유효하면 기존 cache_name 반환.
    만료/미존재 시 새 CachedContent 생성 후 등록.
    """
    # 캐시 유효성 확인
    if cache_key in _explicit_cache_registry:
        cache_name, expires_at = _explicit_cache_registry[cache_key]
        if time.time() < expires_at - 60:  # 만료 1분 전까지 재사용
            return cache_name

    # 신규 캐시 객체 생성 (architecture_plan.md §4.2 명시적 캐싱)
    from datetime import timedelta

    # 초거대 문서를 캐시 contents에 등록
    cache_contents = [
        {
            "role": "user",
            "parts": [
                f"문서 유형: {document_type}\n"
                f"{'대상 종목: ' + ticker + chr(10) if ticker else ''}"
                f"[문서 전문]\n{document_text}"
            ],
        }
    ]

    cached_content = gemini_caching.CachedContent.create(
        model=settings.GEMINI_MODEL,
        contents=cache_contents,
        system_instruction=(
            "당신은 투자 분석 전문 AI입니다. "
            "아래 문서는 캐시된 기업 공시 자료입니다. "
            "사용자의 질문에 따라 투자자 관점의 분석을 제공하세요."
        ),
        ttl=timedelta(seconds=ttl_seconds),
        display_name=f"doc_cache_{cache_key[:40]}",
    )

    cache_name = cached_content.name
    _explicit_cache_registry[cache_key] = (
        cache_name,
        time.time() + ttl_seconds,
    )
    return cache_name


async def generate_document_summary(
    document_text: str,
    document_type: str,
    ticker: str | None = None,
    user_question: str = "핵심 내용을 투자자 관점에서 요약해 주세요.",
    ttl_seconds: int | None = None,
) -> dict[str, Any]:
    """
    초거대 문서 요약 생성 (명시적 캐싱 적용).

    architecture_plan.md §4.2:
      어닝스 콜 대본, 증권사 리포트 → TTL 지정 캐시 객체 사전 로드
      다수 사용자가 같은 문서 질의 시 90%+ 토큰 비용 절감

    Args:
        document_text: 원문 텍스트 (어닝스 콜 대본 등)
        document_type: "earnings_call" | "analyst_report" | "dart_filing"
        ticker: 종목 코드 (선택)
        user_question: 사용자 질문
        ttl_seconds: 캐시 TTL (기본값: settings.GEMINI_CACHE_TTL_SECONDS)

    Returns:
        report, usage, cache_hit, cache_name, generated_at
    """
    _ttl = ttl_seconds or settings.GEMINI_CACHE_TTL_SECONDS

    # 캐시 키 생성 (문서 유형 + 종목 + 내용 앞 200자 해시)
    import hashlib
    content_hash = hashlib.sha256(document_text[:500].encode()).hexdigest()[:16]
    cache_key = f"{document_type}_{ticker or 'common'}_{content_hash}"

    analysis_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # 문서 길이 확인 (명시적 캐싱은 최소 32K 토큰 이상 효과적)
    estimated_tokens = len(document_text) // 4
    use_explicit_cache = estimated_tokens >= 8000  # 약 3만 2천 자 이상

    if use_explicit_cache:
        cache_name = _get_or_create_explicit_cache(
            cache_key, document_text, document_type, ticker, _ttl
        )
        model = _get_model(cache_name=cache_name)
        response = model.generate_content(
            contents=user_question,
            generation_config=genai.GenerationConfig(
                temperature=0.2,
                max_output_tokens=3000,
            ),
        )
        cache_hit = True
    else:
        # 소형 문서는 암시적 캐싱으로 처리
        messages = build_document_summary_prompt(document_text, document_type, ticker)
        model = _get_model()
        response = model.generate_content(
            contents=messages,
            generation_config=genai.GenerationConfig(
                temperature=0.2,
                max_output_tokens=3000,
            ),
        )
        cache_hit = False
        cache_key = None

    usage = response.usage_metadata
    cached_tokens = getattr(usage, "cached_content_token_count", 0) or 0

    return {
        "report": response.text,
        "usage": {
            "prompt_tokens": usage.prompt_token_count,
            "output_tokens": usage.candidates_token_count,
            "cached_tokens": cached_tokens,
            "total_tokens": usage.total_token_count,
        },
        "cache_hit": cache_hit,
        "cache_key": cache_key,
        "model": settings.GEMINI_MODEL,
        "generated_at": analysis_time,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. 범용 Gemini 호출 — 지정학적 리스크 분석 등 커스텀 프롬프트
# ─────────────────────────────────────────────────────────────────────────────

async def call_gemini_raw(
    messages: list[dict],
    temperature: float = 0.3,
    max_output_tokens: int = 3000,
) -> dict[str, Any]:
    """
    커스텀 messages 배열로 Gemini API 직접 호출.

    generate_portfolio_report / generate_document_summary 의
    표준 파이프라인에 맞지 않는 커스텀 프롬프트(지정학적 리스크 분석 등)에 활용.

    Args:
        messages:           Gemini content 배열 (role + parts)
        temperature:        창의성 조정 (금융 분석: 0.3 권장)
        max_output_tokens:  최대 출력 토큰

    Returns:
        {
          "text": str,       # 생성된 텍스트
          "usage": dict,     # 토큰 사용량
          "model": str,
          "generated_at": str,
        }
    """
    analysis_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    model = _get_model()

    response = model.generate_content(
        contents=messages,
        generation_config=genai.GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            top_p=0.9,
        ),
    )

    usage = response.usage_metadata
    cached_tokens = getattr(usage, "cached_content_token_count", 0) or 0

    return {
        "text": response.text,
        "usage": {
            "prompt_tokens": usage.prompt_token_count,
            "output_tokens": usage.candidates_token_count,
            "cached_tokens": cached_tokens,
            "total_tokens": usage.total_token_count,
        },
        "model": settings.GEMINI_MODEL,
        "generated_at": analysis_time,
    }
