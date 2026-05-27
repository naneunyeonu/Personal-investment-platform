"""
지정학적 리스크 분석 Celery 태스크 (architecture_plan.md §7)

이벤트 흐름:
  사용자 → POST /supply-chain/risk-analysis
  → FastAPI: 공급망 노드 DB 조회 → task_id 즉시 반환
  → Celery(ai_reports 큐): Gemini 분석 비동기 처리
    ① 공급망 노드 컨텍스트 주입 (DB 조회 결과)
    ② build_risk_analysis_prompt() → 3-layer 프롬프트 구성
    ③ Gemini API 호출 → 영향 노드 목록 + 파급 효과 + 포트폴리오 리스크 추출
    ④ 구조화된 결과 파싱 (AffectedNodeInfo 목록)
  → Redis result backend에 GeopoliticalRiskResponse 저장

파이프라인 진행 단계:
  10% context_loading    — Celery 역직렬화 + 공급망 컨텍스트 구성
  40% building_prompt    — 프롬프트 조립
  60% calling_gemini     — Gemini API 호출
  90% parsing_result     — 영향 노드 파싱 + 결과 구조화
"""

import asyncio
import re
from typing import Any

from celery import Task
from celery.utils.log import get_task_logger

from app.worker.celery_app import celery_app

logger = get_task_logger(__name__)


@celery_app.task(
    bind=True,
    name="app.worker.tasks.risk_analysis_tasks.analyze_geopolitical_risk_task",
    queue="ai_reports",
    max_retries=2,
    default_retry_delay=60,
    soft_time_limit=180,
    time_limit=210,
)
def analyze_geopolitical_risk_task(
    self: Task,
    news_text: str,
    portfolio_tickers: list[str],
    user_question: str,
    supply_chain_nodes: list[dict],
    user_id: str,
) -> dict[str, Any]:
    """
    지정학적 리스크 분석 Celery 태스크.

    Args:
        news_text:           분석할 지정학적 이벤트 뉴스 텍스트
        portfolio_tickers:   포트폴리오 보유 종목 티커 목록
        user_question:       사용자 분석 질문
        supply_chain_nodes:  DB에서 조회한 공급망 노드 목록 (dict 직렬화 형태)
        user_id:             요청 사용자 ID (로깅용)

    Returns:
        GeopoliticalRiskResponse 딕셔너리 (Redis에 저장)
    """
    logger.info(
        "Starting geopolitical risk analysis | task=%s tickers=%s nodes=%d",
        self.request.id,
        portfolio_tickers,
        len(supply_chain_nodes),
    )

    self.update_state(state="STARTED", meta={"progress": 10, "step": "context_loading"})

    try:
        from app.services.ai.gemini_service import call_gemini_raw
        from app.services.ai.prompt_builder import build_risk_analysis_prompt

        # ── 프롬프트 구성 ────────────────────────────────────────────────
        self.update_state(state="STARTED", meta={"progress": 40, "step": "building_prompt"})

        messages = build_risk_analysis_prompt(
            news_text=news_text,
            portfolio_tickers=portfolio_tickers,
            supply_chain_nodes=supply_chain_nodes,
            user_question=user_question,
        )

        # ── Gemini API 호출 ─────────────────────────────────────────────
        self.update_state(state="STARTED", meta={"progress": 60, "step": "calling_gemini"})

        gemini_result = asyncio.run(call_gemini_raw(messages))

        # ── 결과 파싱 ────────────────────────────────────────────────────
        self.update_state(state="STARTED", meta={"progress": 90, "step": "parsing_result"})

        raw_text: str = gemini_result.get("text", "")
        affected_nodes = _parse_affected_nodes(raw_text, supply_chain_nodes)

        final_result = {
            "task_id": self.request.id,
            "user_id": user_id,
            "portfolio_tickers": portfolio_tickers,
            "supply_chain_nodes_count": len(supply_chain_nodes),
            "event_summary": _extract_section(raw_text, "이벤트 요약"),
            "affected_nodes": affected_nodes,
            "ripple_summary": _extract_section(raw_text, "공급망 파급 경로"),
            "portfolio_impact": _extract_section(raw_text, "포트폴리오 투자 관점 평가"),
            "raw_report": raw_text,
            "usage": gemini_result.get("usage", {}),
        }

        logger.info(
            "Geopolitical risk analysis completed | task=%s affected_nodes=%d tokens=%s",
            self.request.id,
            len(affected_nodes),
            gemini_result.get("usage", {}).get("total_tokens", "?"),
        )
        return final_result

    except Exception as exc:
        logger.error(
            "Geopolitical risk analysis failed | task=%s error=%s",
            self.request.id,
            exc,
        )
        raise self.retry(exc=exc, countdown=60)


# ── 결과 파싱 헬퍼 ───────────────────────────────────────────────────────────

def _extract_section(text: str, section_name: str) -> str:
    """
    Gemini 응답에서 특정 섹션 추출.
    '■ {section_name}' 헤더와 다음 '■' 사이의 텍스트를 반환.
    """
    pattern = rf"■\s*{re.escape(section_name)}(.*?)(?=■|\Z)"
    match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return text[:500] if text else "분석 결과 없음"


def _parse_affected_nodes(
    raw_text: str,
    supply_chain_nodes: list[dict],
) -> list[dict]:
    """
    Gemini 응답 텍스트에서 영향 받는 노드 목록을 파싱.

    전략:
      1. '직접 영향 노드 목록' 섹션에서 노드명 추출
      2. DB 공급망 노드와 매칭 시도 (이름 포함 매칭)
      3. 매칭 성공 → node_id 포함, 실패 → AI 추론 노드로 반환

    심각도 분류:
      '치명적' → CRITICAL, '심각' → HIGH, '보통' → MEDIUM, '경미' → LOW
    """
    # 영향 노드 섹션 추출
    section = _extract_section(raw_text, "직접 영향 노드 목록")
    if not section:
        return []

    # 노드명 매핑 (DB 데이터)
    name_to_node: dict[str, dict] = {
        node["name"].lower(): node for node in supply_chain_nodes
    }
    ticker_to_node: dict[str, dict] = {
        node["ticker"].upper(): node
        for node in supply_chain_nodes
        if node.get("ticker")
    }

    affected: list[dict] = []

    # '• 노드명' 또는 '-  노드명' 패턴으로 행 분리
    lines = [
        ln.strip().lstrip("•-–—").strip()
        for ln in section.split("\n")
        if ln.strip() and any(c in ln for c in ["•", "-", "–", "|"])
    ]

    seen_names: set[str] = set()
    for line in lines:
        if not line or len(line) < 3:
            continue

        # 심각도 탐지
        severity = "보통"
        if "치명" in line or "CRITICAL" in line.upper():
            severity = "치명적"
        elif "심각" in line or "HIGH" in line.upper():
            severity = "심각"
        elif "경미" in line or "LOW" in line.upper():
            severity = "경미"

        # 영향 유형 탐지
        impact_type = "직접 영향"
        if "간접" in line or "파급" in line:
            impact_type = "간접 파급"
        elif "하위" in line or "의존" in line:
            impact_type = "하위 의존성"

        # 노드명 추출 (첫 번째 | 이전 텍스트)
        raw_name = line.split("|")[0].strip()
        if not raw_name or raw_name.lower() in seen_names:
            continue
        seen_names.add(raw_name.lower())

        # DB 매칭
        matched_node: dict | None = None
        lower_name = raw_name.lower()
        for key, node in name_to_node.items():
            if key in lower_name or lower_name in key:
                matched_node = node
                break
        if not matched_node:
            # 티커로 재시도
            for word in re.findall(r"\b[A-Z]{1,6}\b", raw_name):
                if word in ticker_to_node:
                    matched_node = ticker_to_node[word]
                    break

        affected.append({
            "node_id": matched_node["id"] if matched_node else None,
            "node_name": raw_name,
            "ticker": matched_node.get("ticker") if matched_node else None,
            "country_code": matched_node.get("country_code") if matched_node else None,
            "impact_type": impact_type,
            "impact_severity": severity,
            "impact_description": line[:200],
        })

    # 매칭된 노드 우선, 최대 15개
    affected.sort(key=lambda x: (x["node_id"] is None, x["impact_severity"]))
    return affected[:15]
