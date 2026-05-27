"""
공급망(밸류체인) 시각화 라우터 (architecture_plan.md §7)

엔드포인트 목록:
──────────────────────────────────────────────────────────────────────────────
  POST   /supply-chain/nodes              — 노드 생성 (관리자 또는 인증 사용자)
  GET    /supply-chain/nodes              — 노드 목록 (필터: ticker/country/risk)
  GET    /supply-chain/nodes/{id}         — 노드 상세
  PATCH  /supply-chain/nodes/{id}/risk    — 리스크 수준 업데이트 (AI 분석 결과 반영)
  DELETE /supply-chain/nodes/{id}         — 노드 삭제
  POST   /supply-chain/edges              — 에지 생성
  GET    /supply-chain/nodes/{id}/edges   — 특정 노드의 에지 목록
  GET    /supply-chain/nodes/{id}/impact  — 하위 파급 영향 트래버설 (최대 3 depth)

  ── 지도 시각화 형식 ──
  GET    /supply-chain/geojson            — GeoJSON FeatureCollection (Mapbox/Leaflet)
  GET    /supply-chain/flow               — Node-Flow JSON (D3/React Flow)

  ── AI 지정학적 리스크 분석 ──
  POST   /supply-chain/risk-analysis      — Gemini 지정학적 리스크 분석 요청 (비동기)
──────────────────────────────────────────────────────────────────────────────

핵심 제약: 실제 매수/매도 기능 없음. 분석 서포트 전용.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_active_user
from app.core.enums import NodeRiskLevel
from app.db.session import get_db
from app.models.user import User
from app.schemas.ai_report import TaskAcceptedResponse
from app.schemas.supply_chain import (
    GeoJSONFeatureCollection,
    GeopoliticalRiskRequest,
    NodeFlowGraph,
    SupplyChainEdgeCreate,
    SupplyChainEdgeResponse,
    SupplyChainNodeCreate,
    SupplyChainNodeResponse,
    SupplyChainNodeUpdate,
)
from app.services.supply_chain_service import (
    build_geojson,
    build_node_flow_graph,
    create_edge,
    create_node,
    delete_node,
    get_downstream_impact,
    get_node,
    list_edges_for_node,
    list_nodes,
    update_node_risk,
)
from app.worker.tasks.risk_analysis_tasks import analyze_geopolitical_risk_task

router = APIRouter(prefix="/supply-chain", tags=["Supply Chain"])


# ─────────────────────────────────────────────────────────────────────────────
# 노드 CRUD
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/nodes",
    response_model=SupplyChainNodeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="공급망 노드 생성",
    description="기업, 공장, 항구, 물류 허브 등 공급망 노드를 등록합니다.",
)
async def create_supply_chain_node(
    req: SupplyChainNodeCreate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SupplyChainNodeResponse:
    node = await create_node(db, req)
    return SupplyChainNodeResponse.model_validate(node)


@router.get(
    "/nodes",
    response_model=list[SupplyChainNodeResponse],
    summary="공급망 노드 목록 조회",
    description=(
        "공급망 노드 목록을 조회합니다.\n\n"
        "**필터 파라미터:**\n"
        "- `ticker`: 특정 기업 티커의 노드만 반환\n"
        "- `country_code`: ISO 3166-1 국가 코드 필터\n"
        "- `risk_level`: LOW/MEDIUM/HIGH/CRITICAL 리스크 필터"
    ),
)
async def list_supply_chain_nodes(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    ticker: str | None = Query(None, description="종목 티커 필터 (예: AAPL)"),
    country_code: str | None = Query(None, description="국가 코드 필터 (예: KR, US, TW)"),
    risk_level: NodeRiskLevel | None = Query(None, description="리스크 수준 필터"),
) -> list[SupplyChainNodeResponse]:
    nodes = await list_nodes(db, ticker=ticker, country_code=country_code, risk_level=risk_level)
    return [SupplyChainNodeResponse.model_validate(n) for n in nodes]


@router.get(
    "/nodes/{node_id}",
    response_model=SupplyChainNodeResponse,
    summary="공급망 노드 상세 조회",
)
async def get_supply_chain_node(
    node_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SupplyChainNodeResponse:
    node = await get_node(db, node_id)
    if not node:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Supply chain node {node_id} not found",
        )
    return SupplyChainNodeResponse.model_validate(node)


@router.patch(
    "/nodes/{node_id}/risk",
    response_model=SupplyChainNodeResponse,
    summary="노드 리스크 수준 업데이트",
    description=(
        "지정학적 이벤트 발생 시 AI 분석 결과를 바탕으로 노드의 위험 수준을 갱신합니다.\n\n"
        "risk_level을 CRITICAL로 업데이트하면 프론트엔드 지도에서 경고 표시됩니다."
    ),
)
async def update_supply_chain_node_risk(
    node_id: uuid.UUID,
    req: SupplyChainNodeUpdate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SupplyChainNodeResponse:
    node = await update_node_risk(db, node_id, req)
    if not node:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Supply chain node {node_id} not found",
        )
    return SupplyChainNodeResponse.model_validate(node)


@router.delete(
    "/nodes/{node_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="공급망 노드 삭제",
)
async def delete_supply_chain_node(
    node_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    deleted = await delete_node(db, node_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Supply chain node {node_id} not found",
        )


# ─────────────────────────────────────────────────────────────────────────────
# 에지 관리
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/edges",
    response_model=SupplyChainEdgeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="공급망 에지(의존 관계) 생성",
    description=(
        "두 노드 간의 공급망 의존 관계를 등록합니다.\n\n"
        "- `dependency_score`: 0.0(무관) ~ 1.0(완전 의존)\n"
        "- 0.7 이상이면 source 노드 장애 시 target 노드에 심각한 영향"
    ),
)
async def create_supply_chain_edge(
    req: SupplyChainEdgeCreate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SupplyChainEdgeResponse:
    # source/target 노드 존재 확인
    source = await get_node(db, req.source_node_id)
    target = await get_node(db, req.target_node_id)
    if not source or not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source or target node not found",
        )
    edge = await create_edge(db, req)
    return SupplyChainEdgeResponse.model_validate(edge)


@router.get(
    "/nodes/{node_id}/edges",
    response_model=list[SupplyChainEdgeResponse],
    summary="노드의 에지 목록 조회",
    description="특정 노드에 연결된 모든 공급망 에지(출발 + 도착 방향 포함)를 반환합니다.",
)
async def list_node_edges(
    node_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[SupplyChainEdgeResponse]:
    edges = await list_edges_for_node(db, node_id)
    return [SupplyChainEdgeResponse.model_validate(e) for e in edges]


# ─────────────────────────────────────────────────────────────────────────────
# 파급 효과 트래버설
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/nodes/{node_id}/impact",
    summary="하위 파급 영향 분석",
    description=(
        "특정 노드가 차단/중단되었을 때 영향 받는 하위 노드를 BFS로 탐색합니다.\n\n"
        "- 최대 3 depth 탐색 (공급망 3단계)\n"
        "- `path_score`: 의존도 누적 점수 (높을수록 직접 영향)\n"
        "- dependency_score 0.7+ 에지가 연결된 노드는 치명적 영향"
    ),
)
async def get_node_downstream_impact(
    node_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    max_depth: int = Query(3, ge=1, le=5, description="탐색 최대 depth (1~5)"),
) -> list[dict]:
    node = await get_node(db, node_id)
    if not node:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Supply chain node {node_id} not found",
        )
    return await get_downstream_impact(db, node_id, max_depth=max_depth)


# ─────────────────────────────────────────────────────────────────────────────
# 지도 시각화 형식 엔드포인트
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/geojson",
    response_model=GeoJSONFeatureCollection,
    summary="GeoJSON FeatureCollection 반환 (Mapbox / Leaflet)",
    description=(
        "공급망 노드를 **GeoJSON FeatureCollection** 형식으로 반환합니다.\n\n"
        "- 노드 → `Feature(geometry=Point, properties={...})`\n"
        "- 에지 → `Feature(geometry=LineString, ...)` (`include_edges=true` 시)\n\n"
        "**Mapbox GL JS 예시:**\n"
        "```js\n"
        "map.addSource('supply-chain', { type: 'geojson', data: response })\n"
        "```"
    ),
)
async def get_supply_chain_geojson(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    tickers: list[str] | None = Query(
        None,
        description="필터할 티커 목록 (미입력 시 전체 반환)",
    ),
    include_edges: bool = Query(True, description="에지(LineString) 포함 여부"),
) -> GeoJSONFeatureCollection:
    return await build_geojson(db, tickers=tickers, include_edges=include_edges)


@router.get(
    "/flow",
    response_model=NodeFlowGraph,
    summary="Node-Flow 그래프 반환 (D3.js / React Flow)",
    description=(
        "공급망을 **React Flow / D3.js 호환 NodeFlowGraph** 형식으로 반환합니다.\n\n"
        "- 위도·경도 → 캔버스 좌표 자동 변환\n"
        "- `risk_color`: 리스크 수준에 따른 시각화 색상 포함\n"
        "- `stroke_width`: 의존도 점수 기반 에지 두께 (1~5px)"
    ),
)
async def get_supply_chain_flow(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    tickers: list[str] | None = Query(
        None,
        description="필터할 티커 목록 (미입력 시 전체 반환)",
    ),
) -> NodeFlowGraph:
    return await build_node_flow_graph(db, tickers=tickers)


# ─────────────────────────────────────────────────────────────────────────────
# AI 지정학적 리스크 분석
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/risk-analysis",
    response_model=TaskAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="지정학적 리스크 AI 분석 요청",
    description=(
        "뉴스 텍스트 + 포트폴리오 티커를 입력하면 Gemini AI가:\n\n"
        "1. 이벤트의 공급망 파급 경로를 파악\n"
        "2. 영향 받는 공급망 노드(기업/공장/항구)를 특정\n"
        "3. 포트폴리오 투자 관점의 리스크 평가 리포트 생성\n\n"
        "**비동기 처리**: task_id를 즉시 반환, `GET /ai/reports/tasks/{task_id}`로 폴링\n\n"
        "**입력 예시:**\n"
        "```json\n"
        "{\n"
        "  \"news_text\": \"대만해협 긴장 고조로 TSMC 공장 가동 중단 우려\",\n"
        "  \"portfolio_tickers\": [\"AAPL\", \"NVDA\", \"005930\"]\n"
        "}\n"
        "```"
    ),
)
async def request_geopolitical_risk_analysis(
    req: GeopoliticalRiskRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TaskAcceptedResponse:
    # 포트폴리오 티커와 관련된 공급망 노드 조회 (컨텍스트 주입용)
    supply_chain_nodes = []
    for ticker in req.portfolio_tickers:
        nodes = await list_nodes(db, ticker=ticker)
        for node in nodes:
            supply_chain_nodes.append({
                "id": str(node.id),
                "name": node.name,
                "ticker": node.ticker,
                "node_type": node.node_type.value,
                "country_code": node.country_code,
                "city": node.city,
                "industry_sector": node.industry_sector,
                "description": node.description,
                "risk_level": node.risk_level.value,
            })

    task = analyze_geopolitical_risk_task.delay(
        news_text=req.news_text,
        portfolio_tickers=req.portfolio_tickers,
        user_question=req.question,
        supply_chain_nodes=supply_chain_nodes,
        user_id=str(current_user.id),
    )

    from app.api.v1.routers.ai_report import _poll_url
    return TaskAcceptedResponse(
        task_id=task.id,
        message=(
            f"지정학적 리스크 분석 작업이 등록되었습니다. "
            f"티커: {', '.join(req.portfolio_tickers)}"
        ),
        poll_url=_poll_url(request, task.id),
    )
