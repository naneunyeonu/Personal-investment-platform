"""
공급망 시각화 API Pydantic 스키마

프론트엔드 지도 렌더링을 위한 두 가지 출력 형식:
  1. GeoJSON FeatureCollection  — Mapbox / Leaflet 지도 레이어용
  2. NodeFlowGraph (nodes + edges) — D3.js / React Flow 네트워크 다이어그램용

지정학적 리스크 분석 요청/응답:
  GeopoliticalRiskRequest  — 뉴스 텍스트 + 포트폴리오 티커 목록
  GeopoliticalRiskResponse — Gemini 분석: 영향 노드 목록 + 파급 효과 + task_id
"""

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.enums import NodeRiskLevel, SupplyChainNodeType, SupplyChainRelationType


# ─────────────────────────────────────────────────────────────────────────────
# 공급망 노드 CRUD 스키마
# ─────────────────────────────────────────────────────────────────────────────

class SupplyChainNodeCreate(BaseModel):
    """노드 생성 요청."""
    name: str = Field(..., min_length=1, max_length=200)
    ticker: str | None = Field(None, max_length=20)
    node_type: SupplyChainNodeType
    country_code: str = Field(..., min_length=2, max_length=3)
    city: str | None = Field(None, max_length=100)
    latitude: float | None = Field(None, ge=-90.0, le=90.0)
    longitude: float | None = Field(None, ge=-180.0, le=180.0)
    industry_sector: str | None = Field(None, max_length=100)
    description: str | None = None
    risk_level: NodeRiskLevel = NodeRiskLevel.LOW
    risk_note: str | None = None


class SupplyChainNodeUpdate(BaseModel):
    """노드 부분 업데이트 — 지정학적 리스크 수준 갱신에 주로 사용."""
    name: str | None = Field(None, max_length=200)
    risk_level: NodeRiskLevel | None = None
    risk_note: str | None = None
    description: str | None = None


class SupplyChainNodeResponse(BaseModel):
    """노드 응답 스키마."""
    id: uuid.UUID
    name: str
    ticker: str | None
    node_type: SupplyChainNodeType
    country_code: str
    city: str | None
    latitude: float | None
    longitude: float | None
    industry_sector: str | None
    description: str | None
    risk_level: NodeRiskLevel
    risk_note: str | None

    model_config = {"from_attributes": True}


# ─────────────────────────────────────────────────────────────────────────────
# 공급망 에지 CRUD 스키마
# ─────────────────────────────────────────────────────────────────────────────

class SupplyChainEdgeCreate(BaseModel):
    """에지(의존 관계) 생성 요청."""
    source_node_id: uuid.UUID
    target_node_id: uuid.UUID
    relation_type: SupplyChainRelationType
    dependency_score: float = Field(0.5, ge=0.0, le=1.0)
    annual_value_usd: float | None = Field(None, ge=0)
    description: str | None = None


class SupplyChainEdgeResponse(BaseModel):
    """에지 응답 스키마."""
    id: uuid.UUID
    source_node_id: uuid.UUID
    target_node_id: uuid.UUID
    relation_type: SupplyChainRelationType
    dependency_score: float
    annual_value_usd: float | None
    description: str | None

    model_config = {"from_attributes": True}


# ─────────────────────────────────────────────────────────────────────────────
# GeoJSON 응답 (Mapbox / Leaflet)
# ─────────────────────────────────────────────────────────────────────────────

class GeoJSONGeometry(BaseModel):
    """GeoJSON Geometry (Point / LineString)."""
    type: Literal["Point", "LineString"]
    coordinates: list[float] | list[list[float]]


class GeoJSONFeature(BaseModel):
    """GeoJSON Feature — 단일 노드 또는 에지."""
    type: Literal["Feature"] = "Feature"
    geometry: GeoJSONGeometry | None
    properties: dict[str, Any]


class GeoJSONFeatureCollection(BaseModel):
    """
    GeoJSON FeatureCollection — Mapbox/Leaflet 직접 주입 가능한 형식.

    properties 필드 구성:
      노드: {id, name, ticker, node_type, country_code, risk_level, risk_note}
      에지: {id, source_node_id, target_node_id, relation_type, dependency_score}
    """
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[GeoJSONFeature]
    total_nodes: int = 0
    total_edges: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# Node-Flow 그래프 (D3.js / React Flow)
# ─────────────────────────────────────────────────────────────────────────────

class FlowNode(BaseModel):
    """
    React Flow / D3 노드 형식.
    id는 UUID 문자열, position은 위도·경도를 UI 좌표로 변환.
    """
    id: str                          # UUID 문자열
    type: str = "supplyChainNode"    # React Flow custom node type
    data: dict[str, Any]             # 렌더링에 필요한 전체 속성
    position: dict[str, float]       # {"x": ..., "y": ...}


class FlowEdge(BaseModel):
    """React Flow / D3 에지 형식."""
    id: str
    source: str                      # source node id (문자열)
    target: str                      # target node id (문자열)
    label: str | None = None
    data: dict[str, Any]


class NodeFlowGraph(BaseModel):
    """
    React Flow / D3 네트워크 다이어그램용 JSON.
    공급망 의존 관계를 방향성 그래프로 표현.
    """
    nodes: list[FlowNode]
    edges: list[FlowEdge]
    total_nodes: int = 0
    total_edges: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# 지정학적 리스크 분석 요청/응답
# ─────────────────────────────────────────────────────────────────────────────

class GeopoliticalRiskRequest(BaseModel):
    """
    지정학적 리스크 분석 요청.

    뉴스 텍스트 + 포트폴리오 티커 → Gemini AI가 영향 노드 특정.
    Celery ai_reports 큐에서 비동기 처리, task_id 즉시 반환.
    """
    news_text: str = Field(
        ...,
        min_length=10,
        description="분석할 지정학적 이벤트 뉴스 텍스트 (해협 봉쇄, 공장 가동 중단 등)",
        examples=[
            "대만해협 분쟁 격화로 TSMC의 주요 파운드리 공장 가동이 72시간 내 중단될 위기에 처했습니다."
        ],
    )
    portfolio_tickers: list[str] = Field(
        ...,
        min_length=1,
        description="포트폴리오 보유 종목 티커 목록 (공급망 필터링 기준)",
        examples=[["AAPL", "NVDA", "005930"]],
    )
    question: str = Field(
        default="이 이벤트가 내 포트폴리오의 공급망에 미치는 파급 효과를 분석해 주세요.",
        description="AI에게 전달할 분석 질문",
    )


class AffectedNodeInfo(BaseModel):
    """AI가 특정한 영향 받는 노드 정보."""
    node_id: str | None = None       # DB에 등록된 노드 ID (없을 수 있음)
    node_name: str
    ticker: str | None = None
    country_code: str | None = None
    impact_type: str                  # "직접 영향" / "간접 파급" / "하위 의존성"
    impact_severity: str              # "치명적" / "심각" / "보통" / "경미"
    impact_description: str


class GeopoliticalRiskResponse(BaseModel):
    """
    지정학적 리스크 분석 결과 (Celery 태스크 완료 후 반환).

    affected_nodes: AI가 파급 효과를 받는다고 판단한 공급망 노드 목록
    ripple_summary: 파급 효과 자연어 요약
    portfolio_impact: 포트폴리오 전체 관점의 리스크 평가
    """
    task_id: str
    event_summary: str               # AI가 정리한 이벤트 요약
    affected_nodes: list[AffectedNodeInfo]
    ripple_summary: str              # 공급망 파급 효과 자연어 요약
    portfolio_impact: str            # 포트폴리오 투자 관점 영향 분석
    raw_report: str                  # Gemini 원문 응답
    usage: dict[str, Any]
