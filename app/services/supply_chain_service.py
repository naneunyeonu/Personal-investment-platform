"""
공급망 서비스 계층 (architecture_plan.md §7)

데이터 조회 및 GeoJSON / NodeFlow 변환 담당.
라우터는 이 서비스를 통해서만 DB에 접근.
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.enums import NodeRiskLevel
from app.models.supply_chain import SupplyChainEdge, SupplyChainNode
from app.schemas.supply_chain import (
    FlowEdge,
    FlowNode,
    GeoJSONFeature,
    GeoJSONFeatureCollection,
    GeoJSONGeometry,
    NodeFlowGraph,
    SupplyChainEdgeCreate,
    SupplyChainEdgeResponse,
    SupplyChainNodeCreate,
    SupplyChainNodeResponse,
    SupplyChainNodeUpdate,
)


# ── 노드 CRUD ────────────────────────────────────────────────────────────────

async def create_node(
    db: AsyncSession,
    data: SupplyChainNodeCreate,
) -> SupplyChainNode:
    node = SupplyChainNode(**data.model_dump())
    db.add(node)
    await db.commit()
    await db.refresh(node)
    return node


async def get_node(db: AsyncSession, node_id: uuid.UUID) -> SupplyChainNode | None:
    result = await db.execute(
        select(SupplyChainNode).where(SupplyChainNode.id == node_id)
    )
    return result.scalar_one_or_none()


async def list_nodes(
    db: AsyncSession,
    ticker: str | None = None,
    country_code: str | None = None,
    risk_level: NodeRiskLevel | None = None,
) -> list[SupplyChainNode]:
    """노드 목록 조회 (필터: ticker, country, risk_level)."""
    q = select(SupplyChainNode)
    if ticker:
        q = q.where(SupplyChainNode.ticker == ticker.upper())
    if country_code:
        q = q.where(SupplyChainNode.country_code == country_code.upper())
    if risk_level:
        q = q.where(SupplyChainNode.risk_level == risk_level)
    result = await db.execute(q.order_by(SupplyChainNode.name))
    return list(result.scalars().all())


async def update_node_risk(
    db: AsyncSession,
    node_id: uuid.UUID,
    data: SupplyChainNodeUpdate,
) -> SupplyChainNode | None:
    node = await get_node(db, node_id)
    if not node:
        return None
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(node, field, value)
    await db.commit()
    await db.refresh(node)
    return node


async def delete_node(db: AsyncSession, node_id: uuid.UUID) -> bool:
    node = await get_node(db, node_id)
    if not node:
        return False
    await db.delete(node)
    await db.commit()
    return True


# ── 에지 CRUD ────────────────────────────────────────────────────────────────

async def create_edge(
    db: AsyncSession,
    data: SupplyChainEdgeCreate,
) -> SupplyChainEdge:
    edge = SupplyChainEdge(**data.model_dump())
    db.add(edge)
    await db.commit()
    await db.refresh(edge)
    return edge


async def list_edges_for_node(
    db: AsyncSession,
    node_id: uuid.UUID,
) -> list[SupplyChainEdge]:
    """특정 노드의 모든 출발 + 도착 에지."""
    result = await db.execute(
        select(SupplyChainEdge).where(
            (SupplyChainEdge.source_node_id == node_id)
            | (SupplyChainEdge.target_node_id == node_id)
        )
    )
    return list(result.scalars().all())


# ── GeoJSON 변환 ─────────────────────────────────────────────────────────────

async def build_geojson(
    db: AsyncSession,
    tickers: list[str] | None = None,
    include_edges: bool = True,
) -> GeoJSONFeatureCollection:
    """
    공급망 데이터를 GeoJSON FeatureCollection으로 변환.
    Mapbox / Leaflet에 직접 주입 가능한 형식.

    노드 → GeoJSON Point Feature
    에지 → GeoJSON LineString Feature (include_edges=True 시)
    """
    # 노드 조회
    q = select(SupplyChainNode)
    if tickers:
        upper_tickers = [t.upper() for t in tickers]
        q = q.where(SupplyChainNode.ticker.in_(upper_tickers))
    node_result = await db.execute(q)
    nodes: list[SupplyChainNode] = list(node_result.scalars().all())

    features: list[GeoJSONFeature] = []
    node_ids = {n.id for n in nodes}
    node_coord_map: dict[uuid.UUID, list[float]] = {}

    # 노드 → Point Feature
    for node in nodes:
        coords = None
        if node.latitude is not None and node.longitude is not None:
            coords = [node.longitude, node.latitude]  # GeoJSON: [lon, lat]
            node_coord_map[node.id] = coords

        features.append(
            GeoJSONFeature(
                geometry=GeoJSONGeometry(type="Point", coordinates=coords or [0.0, 0.0])
                if coords else None,
                properties={
                    "id": str(node.id),
                    "name": node.name,
                    "ticker": node.ticker,
                    "node_type": node.node_type.value,
                    "country_code": node.country_code,
                    "city": node.city,
                    "industry_sector": node.industry_sector,
                    "risk_level": node.risk_level.value,
                    "risk_note": node.risk_note,
                    "description": node.description,
                    "feature_type": "node",
                },
            )
        )

    total_edges = 0
    if include_edges and node_ids:
        # 필터된 노드 범위 내 에지만 조회
        edge_q = select(SupplyChainEdge).where(
            SupplyChainEdge.source_node_id.in_(node_ids)
            & SupplyChainEdge.target_node_id.in_(node_ids)
        )
        edge_result = await db.execute(edge_q)
        edges: list[SupplyChainEdge] = list(edge_result.scalars().all())
        total_edges = len(edges)

        for edge in edges:
            src_coords = node_coord_map.get(edge.source_node_id)
            tgt_coords = node_coord_map.get(edge.target_node_id)

            line_coords = None
            if src_coords and tgt_coords:
                line_coords = [src_coords, tgt_coords]

            features.append(
                GeoJSONFeature(
                    geometry=GeoJSONGeometry(
                        type="LineString",
                        coordinates=line_coords or [[0.0, 0.0], [0.0, 0.0]],
                    )
                    if line_coords else None,
                    properties={
                        "id": str(edge.id),
                        "source_node_id": str(edge.source_node_id),
                        "target_node_id": str(edge.target_node_id),
                        "relation_type": edge.relation_type.value,
                        "dependency_score": edge.dependency_score,
                        "annual_value_usd": (
                            float(edge.annual_value_usd)
                            if edge.annual_value_usd else None
                        ),
                        "description": edge.description,
                        "feature_type": "edge",
                    },
                )
            )

    return GeoJSONFeatureCollection(
        features=features,
        total_nodes=len(nodes),
        total_edges=total_edges,
    )


# ── Node-Flow 그래프 변환 ─────────────────────────────────────────────────────

_RISK_COLOR = {
    NodeRiskLevel.LOW: "#4CAF50",       # 초록
    NodeRiskLevel.MEDIUM: "#FF9800",    # 주황
    NodeRiskLevel.HIGH: "#F44336",      # 빨강
    NodeRiskLevel.CRITICAL: "#9C27B0",  # 보라 (긴급)
}

_LON_TO_X_SCALE = 3.5   # 경도 → UI x 좌표 배율
_LAT_TO_Y_SCALE = -4.0  # 위도 → UI y 좌표 배율 (y축 반전)


def _coords_to_position(lat: float | None, lon: float | None) -> dict[str, float]:
    """위도·경도 → React Flow 캔버스 좌표 (대략적인 선형 변환)."""
    if lat is None or lon is None:
        return {"x": 0.0, "y": 0.0}
    return {
        "x": round(lon * _LON_TO_X_SCALE, 2),
        "y": round(lat * _LAT_TO_Y_SCALE, 2),
    }


async def build_node_flow_graph(
    db: AsyncSession,
    tickers: list[str] | None = None,
) -> NodeFlowGraph:
    """
    React Flow / D3.js 네트워크 다이어그램용 NodeFlowGraph 생성.

    노드 position: 위도·경도 → 캔버스 좌표 선형 변환.
    에지 data: relation_type, dependency_score → 화살표 두께/색상 조정용.
    """
    q = select(SupplyChainNode).options(
        selectinload(SupplyChainNode.outgoing_edges)
    )
    if tickers:
        upper_tickers = [t.upper() for t in tickers]
        q = q.where(SupplyChainNode.ticker.in_(upper_tickers))
    node_result = await db.execute(q)
    nodes: list[SupplyChainNode] = list(node_result.scalars().all())
    node_ids = {n.id for n in nodes}

    flow_nodes: list[FlowNode] = [
        FlowNode(
            id=str(n.id),
            type="supplyChainNode",
            data={
                "label": n.name,
                "ticker": n.ticker,
                "node_type": n.node_type.value,
                "country_code": n.country_code,
                "city": n.city,
                "industry_sector": n.industry_sector,
                "risk_level": n.risk_level.value,
                "risk_color": _RISK_COLOR.get(n.risk_level, "#4CAF50"),
                "risk_note": n.risk_note,
                "description": n.description,
            },
            position=_coords_to_position(n.latitude, n.longitude),
        )
        for n in nodes
    ]

    # 에지 수집 (노드 범위 내)
    edge_q = select(SupplyChainEdge).where(
        SupplyChainEdge.source_node_id.in_(node_ids)
        & SupplyChainEdge.target_node_id.in_(node_ids)
    )
    edge_result = await db.execute(edge_q)
    edges: list[SupplyChainEdge] = list(edge_result.scalars().all())

    # dependency_score → 에지 두께 (1~5px)
    def _stroke_width(score: float) -> int:
        return max(1, min(5, round(score * 5)))

    flow_edges: list[FlowEdge] = [
        FlowEdge(
            id=str(e.id),
            source=str(e.source_node_id),
            target=str(e.target_node_id),
            label=e.relation_type.value,
            data={
                "relation_type": e.relation_type.value,
                "dependency_score": e.dependency_score,
                "stroke_width": _stroke_width(e.dependency_score),
                "annual_value_usd": (
                    float(e.annual_value_usd) if e.annual_value_usd else None
                ),
                "description": e.description,
            },
        )
        for e in edges
    ]

    return NodeFlowGraph(
        nodes=flow_nodes,
        edges=flow_edges,
        total_nodes=len(flow_nodes),
        total_edges=len(flow_edges),
    )


# ── 리스크 영향 트래버설 ─────────────────────────────────────────────────────

async def get_downstream_impact(
    db: AsyncSession,
    node_id: uuid.UUID,
    max_depth: int = 3,
) -> list[dict[str, Any]]:
    """
    특정 노드의 하위 의존 노드 탐색 (BFS, 최대 depth=3).
    특정 노드가 멈췄을 때 어떤 기업/공장이 영향을 받는지 반환.

    Returns:
        [{"node": SupplyChainNode, "depth": int, "path_score": float}, ...]
    """
    visited: set[uuid.UUID] = set()
    result: list[dict[str, Any]] = []
    queue: list[tuple[uuid.UUID, int, float]] = [(node_id, 0, 1.0)]

    while queue:
        current_id, depth, path_score = queue.pop(0)
        if current_id in visited or depth > max_depth:
            continue
        visited.add(current_id)

        if depth > 0:  # 출발 노드 자신은 결과에서 제외
            node = await get_node(db, current_id)
            if node:
                result.append({
                    "node": SupplyChainNodeResponse.model_validate(node),
                    "depth": depth,
                    "path_score": round(path_score, 3),
                })

        # 해당 노드를 source로 하는 에지 조회
        edge_q = select(SupplyChainEdge).where(
            SupplyChainEdge.source_node_id == current_id
        )
        edge_result = await db.execute(edge_q)
        for edge in edge_result.scalars().all():
            if edge.target_node_id not in visited:
                queue.append(
                    (
                        edge.target_node_id,
                        depth + 1,
                        path_score * edge.dependency_score,
                    )
                )

    # 파급 강도(path_score) 내림차순 정렬
    result.sort(key=lambda x: x["path_score"], reverse=True)
    return result
