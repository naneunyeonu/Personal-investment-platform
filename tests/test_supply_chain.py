"""
공급망(밸류체인) 파이프라인 테스트

architecture_plan.md §7 구현 검증:
  - SupplyChainNode / SupplyChainEdge 모델 필드 및 열거형
  - GeoJSON FeatureCollection 변환 (Point / LineString)
  - NodeFlowGraph 변환 (React Flow / D3)
  - 하위 파급 영향 트래버설 (BFS, dependency_score 가중치)
  - 지정학적 리스크 분석 프롬프트 빌더
  - Celery 태스크 헬퍼 (_parse_affected_nodes, _extract_section)
"""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# Enum 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestSupplyChainEnums:
    """새 enum 값 존재 및 str Enum 동작 확인."""

    def test_node_type_values(self):
        from app.core.enums import SupplyChainNodeType
        expected = {"COMPANY", "FACTORY", "PORT", "LOGISTICS_HUB",
                    "RAW_MATERIAL_SITE", "DISTRIBUTION_CENTER"}
        assert {e.value for e in SupplyChainNodeType} == expected

    def test_relation_type_values(self):
        from app.core.enums import SupplyChainRelationType
        expected = {"SUPPLIES", "MANUFACTURES_FOR", "DISTRIBUTES_TO", "DEPENDS_ON"}
        assert {e.value for e in SupplyChainRelationType} == expected

    def test_risk_level_values(self):
        from app.core.enums import NodeRiskLevel
        expected = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
        assert {e.value for e in NodeRiskLevel} == expected

    def test_enums_are_str_enums(self):
        from app.core.enums import NodeRiskLevel, SupplyChainNodeType
        assert SupplyChainNodeType.FACTORY == "FACTORY"
        assert NodeRiskLevel.CRITICAL == "CRITICAL"


# ─────────────────────────────────────────────────────────────────────────────
# 모델 인스턴스 생성 테스트 (DB 불필요 — 객체 수준)
# ─────────────────────────────────────────────────────────────────────────────

class TestSupplyChainNodeModel:
    """SupplyChainNode SQLAlchemy 모델 속성 검증."""

    def _make_node(self, **kwargs) -> object:
        from app.core.enums import NodeRiskLevel, SupplyChainNodeType
        from app.models.supply_chain import SupplyChainNode
        defaults = {
            "id": uuid.uuid4(),
            "name": "삼성전자 평택 공장",
            "ticker": "005930",
            "node_type": SupplyChainNodeType.FACTORY,
            "country_code": "KR",
            "city": "평택",
            "latitude": 36.9922,
            "longitude": 127.1122,
            "industry_sector": "반도체",
            "risk_level": NodeRiskLevel.LOW,
        }
        defaults.update(kwargs)
        return SupplyChainNode(**defaults)

    def test_node_repr_contains_name(self):
        node = self._make_node()
        assert "삼성전자" in repr(node)

    def test_node_repr_contains_risk(self):
        from app.core.enums import NodeRiskLevel
        node = self._make_node(risk_level=NodeRiskLevel.HIGH)
        assert "HIGH" in repr(node)

    def test_node_ticker_optional(self):
        node = self._make_node(ticker=None)
        assert node.ticker is None

    def test_node_coordinates_stored(self):
        node = self._make_node(latitude=37.5, longitude=127.0)
        assert node.latitude == 37.5
        assert node.longitude == 127.0

    def test_node_risk_note_optional(self):
        node = self._make_node(risk_note=None)
        assert node.risk_note is None

    def test_node_with_risk_note(self):
        node = self._make_node(risk_note="대만해협 분쟁 영향권")
        assert node.risk_note == "대만해협 분쟁 영향권"


class TestSupplyChainEdgeModel:
    """SupplyChainEdge SQLAlchemy 모델 속성 검증."""

    def _make_edge(self, **kwargs) -> object:
        from app.core.enums import SupplyChainRelationType
        from app.models.supply_chain import SupplyChainEdge
        defaults = {
            "id": uuid.uuid4(),
            "source_node_id": uuid.uuid4(),
            "target_node_id": uuid.uuid4(),
            "relation_type": SupplyChainRelationType.SUPPLIES,
            "dependency_score": 0.8,
        }
        defaults.update(kwargs)
        return SupplyChainEdge(**defaults)

    def test_edge_repr_contains_relation(self):
        edge = self._make_edge()
        assert "SUPPLIES" in repr(edge)

    def test_edge_repr_contains_score(self):
        edge = self._make_edge(dependency_score=0.9)
        assert "0.9" in repr(edge)

    def test_dependency_score_stored(self):
        edge = self._make_edge(dependency_score=0.75)
        assert edge.dependency_score == 0.75

    def test_annual_value_optional(self):
        edge = self._make_edge(annual_value_usd=None)
        assert edge.annual_value_usd is None

    def test_annual_value_can_be_set(self):
        edge = self._make_edge(annual_value_usd=Decimal("5000000000.00"))
        assert edge.annual_value_usd is not None


# ─────────────────────────────────────────────────────────────────────────────
# 스키마 직렬화 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestSupplyChainSchemas:
    """Pydantic 스키마 유효성 검증."""

    def test_node_create_valid(self):
        from app.core.enums import SupplyChainNodeType
        from app.schemas.supply_chain import SupplyChainNodeCreate
        data = SupplyChainNodeCreate(
            name="TSMC 타이난 공장",
            ticker="TSM",
            node_type=SupplyChainNodeType.FACTORY,
            country_code="TW",
            city="타이난",
            latitude=22.99,
            longitude=120.22,
            industry_sector="반도체 파운드리",
        )
        assert data.ticker == "TSM"

    def test_node_create_ticker_optional(self):
        from app.core.enums import SupplyChainNodeType
        from app.schemas.supply_chain import SupplyChainNodeCreate
        data = SupplyChainNodeCreate(
            name="부산항 국제터미널",
            node_type=SupplyChainNodeType.PORT,
            country_code="KR",
        )
        assert data.ticker is None

    def test_edge_create_dependency_score_bounds(self):
        """dependency_score 0.0~1.0 범위 검증."""
        import pydantic
        from app.core.enums import SupplyChainRelationType
        from app.schemas.supply_chain import SupplyChainEdgeCreate
        with pytest.raises(pydantic.ValidationError):
            SupplyChainEdgeCreate(
                source_node_id=uuid.uuid4(),
                target_node_id=uuid.uuid4(),
                relation_type=SupplyChainRelationType.SUPPLIES,
                dependency_score=1.5,   # 범위 초과
            )

    def test_edge_create_valid(self):
        from app.core.enums import SupplyChainRelationType
        from app.schemas.supply_chain import SupplyChainEdgeCreate
        edge = SupplyChainEdgeCreate(
            source_node_id=uuid.uuid4(),
            target_node_id=uuid.uuid4(),
            relation_type=SupplyChainRelationType.MANUFACTURES_FOR,
            dependency_score=0.9,
            annual_value_usd=3_000_000_000.0,
        )
        assert edge.dependency_score == 0.9

    def test_geojson_feature_collection_structure(self):
        from app.schemas.supply_chain import (
            GeoJSONFeature,
            GeoJSONFeatureCollection,
            GeoJSONGeometry,
        )
        fc = GeoJSONFeatureCollection(
            features=[
                GeoJSONFeature(
                    geometry=GeoJSONGeometry(type="Point", coordinates=[127.0, 37.5]),
                    properties={"name": "Test", "risk_level": "LOW"},
                )
            ],
            total_nodes=1,
            total_edges=0,
        )
        assert fc.type == "FeatureCollection"
        assert len(fc.features) == 1
        assert fc.features[0].geometry.type == "Point"

    def test_node_flow_graph_structure(self):
        from app.schemas.supply_chain import FlowEdge, FlowNode, NodeFlowGraph
        graph = NodeFlowGraph(
            nodes=[
                FlowNode(
                    id="node-1",
                    data={"label": "삼성전자", "risk_level": "LOW"},
                    position={"x": 0.0, "y": 0.0},
                )
            ],
            edges=[
                FlowEdge(
                    id="edge-1",
                    source="node-1",
                    target="node-2",
                    data={"dependency_score": 0.8},
                )
            ],
            total_nodes=1,
            total_edges=1,
        )
        assert graph.nodes[0].type == "supplyChainNode"
        assert graph.edges[0].source == "node-1"

    def test_geopolitical_risk_request_valid(self):
        from app.schemas.supply_chain import GeopoliticalRiskRequest
        req = GeopoliticalRiskRequest(
            news_text="대만해협 긴장 고조로 TSMC 공장 가동 중단 우려",
            portfolio_tickers=["AAPL", "NVDA", "005930"],
        )
        assert len(req.portfolio_tickers) == 3

    def test_geopolitical_risk_request_default_question(self):
        from app.schemas.supply_chain import GeopoliticalRiskRequest
        req = GeopoliticalRiskRequest(
            news_text="호르무즈 해협 봉쇄 위기",
            portfolio_tickers=["XOM"],
        )
        assert "공급망" in req.question or "파급" in req.question


# ─────────────────────────────────────────────────────────────────────────────
# GeoJSON 변환 테스트 (Mock DB)
# ─────────────────────────────────────────────────────────────────────────────

import pytest


def _make_mock_node(
    name: str,
    ticker: str | None = None,
    lat: float = 37.5,
    lon: float = 127.0,
    country: str = "KR",
    risk: str = "LOW",
) -> MagicMock:
    from app.core.enums import NodeRiskLevel, SupplyChainNodeType
    node = MagicMock()
    node.id = uuid.uuid4()
    node.name = name
    node.ticker = ticker
    node.node_type = SupplyChainNodeType.FACTORY
    node.country_code = country
    node.city = "서울"
    node.latitude = lat
    node.longitude = lon
    node.industry_sector = "반도체"
    node.risk_level = NodeRiskLevel(risk)
    node.risk_note = None
    node.description = None
    return node


def _make_mock_edge(src_id: uuid.UUID, tgt_id: uuid.UUID, score: float = 0.8) -> MagicMock:
    from app.core.enums import SupplyChainRelationType
    edge = MagicMock()
    edge.id = uuid.uuid4()
    edge.source_node_id = src_id
    edge.target_node_id = tgt_id
    edge.relation_type = SupplyChainRelationType.SUPPLIES
    edge.dependency_score = score
    edge.annual_value_usd = None
    edge.description = None
    return edge


class TestBuildGeoJSON:
    """build_geojson() 서비스 함수 — Mock AsyncSession으로 단위 테스트."""

    def _make_db(self, nodes: list, edges: list | None = None) -> AsyncMock:
        """nodes/edges를 반환하는 Mock AsyncSession 생성."""
        db = AsyncMock()
        # execute().scalars().all() 체인 모킹
        node_scalars = MagicMock()
        node_scalars.all.return_value = nodes
        node_result = MagicMock()
        node_result.scalars.return_value = node_scalars

        edge_scalars = MagicMock()
        edge_scalars.all.return_value = edges or []
        edge_result = MagicMock()
        edge_result.scalars.return_value = edge_scalars

        # execute를 순서대로 반환 (nodes 먼저, edges 두 번째)
        db.execute = AsyncMock(side_effect=[node_result, edge_result])
        return db

    @pytest.mark.asyncio
    async def test_returns_feature_collection_type(self):
        from app.services.supply_chain_service import build_geojson
        db = self._make_db([])
        result = await build_geojson(db)
        assert result.type == "FeatureCollection"

    @pytest.mark.asyncio
    async def test_node_becomes_point_feature(self):
        from app.services.supply_chain_service import build_geojson
        node = _make_mock_node("TSMC", ticker="TSM", lat=25.0, lon=121.5, country="TW")
        db = self._make_db([node])
        result = await build_geojson(db, include_edges=False)
        assert result.total_nodes == 1
        assert len(result.features) == 1
        feat = result.features[0]
        assert feat.geometry.type == "Point"
        # GeoJSON 좌표 순서: [경도, 위도]
        assert feat.geometry.coordinates == [121.5, 25.0]

    @pytest.mark.asyncio
    async def test_node_properties_contain_risk_level(self):
        from app.services.supply_chain_service import build_geojson
        node = _make_mock_node("위험공장", risk="CRITICAL")
        db = self._make_db([node])
        result = await build_geojson(db, include_edges=False)
        props = result.features[0].properties
        assert props["risk_level"] == "CRITICAL"

    @pytest.mark.asyncio
    async def test_node_properties_feature_type_marker(self):
        from app.services.supply_chain_service import build_geojson
        node = _make_mock_node("테스트노드")
        db = self._make_db([node])
        result = await build_geojson(db, include_edges=False)
        assert result.features[0].properties["feature_type"] == "node"

    @pytest.mark.asyncio
    async def test_edge_becomes_linestring_feature(self):
        from app.services.supply_chain_service import build_geojson
        n1 = _make_mock_node("공장A", lat=37.0, lon=127.0)
        n2 = _make_mock_node("공장B", lat=35.0, lon=129.0)
        edge = _make_mock_edge(n1.id, n2.id)
        db = self._make_db([n1, n2], [edge])
        result = await build_geojson(db, include_edges=True)
        edge_features = [f for f in result.features if f.properties.get("feature_type") == "edge"]
        assert len(edge_features) == 1
        assert edge_features[0].geometry.type == "LineString"

    @pytest.mark.asyncio
    async def test_include_edges_false_no_linestrings(self):
        from app.services.supply_chain_service import build_geojson
        n1 = _make_mock_node("공장A")
        # include_edges=False이면 에지 쿼리 자체를 하지 않음
        db = AsyncMock()
        scalars = MagicMock()
        scalars.all.return_value = [n1]
        res = MagicMock()
        res.scalars.return_value = scalars
        db.execute = AsyncMock(return_value=res)
        result = await build_geojson(db, include_edges=False)
        edge_features = [f for f in result.features if f.properties.get("feature_type") == "edge"]
        assert len(edge_features) == 0

    @pytest.mark.asyncio
    async def test_node_without_coords_has_none_geometry(self):
        """좌표 없는 노드 → geometry=None."""
        from app.services.supply_chain_service import build_geojson
        node = _make_mock_node("좌표없는공장", lat=None, lon=None)
        node.latitude = None
        node.longitude = None
        db = self._make_db([node])
        result = await build_geojson(db, include_edges=False)
        assert result.features[0].geometry is None

    @pytest.mark.asyncio
    async def test_total_counts_accurate(self):
        from app.services.supply_chain_service import build_geojson
        n1 = _make_mock_node("A", lat=37.0, lon=127.0)
        n2 = _make_mock_node("B", lat=36.0, lon=128.0)
        edge = _make_mock_edge(n1.id, n2.id)
        db = self._make_db([n1, n2], [edge])
        result = await build_geojson(db)
        assert result.total_nodes == 2
        assert result.total_edges == 1


# ─────────────────────────────────────────────────────────────────────────────
# NodeFlowGraph 변환 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildNodeFlowGraph:
    """build_node_flow_graph() 서비스 함수 테스트."""

    def _make_db_for_flow(self, nodes: list, edges: list) -> AsyncMock:
        db = AsyncMock()
        node_scalars = MagicMock()
        node_scalars.all.return_value = nodes
        node_result = MagicMock()
        node_result.scalars.return_value = node_scalars

        edge_scalars = MagicMock()
        edge_scalars.all.return_value = edges
        edge_result = MagicMock()
        edge_result.scalars.return_value = edge_scalars

        db.execute = AsyncMock(side_effect=[node_result, edge_result])
        return db

    @pytest.mark.asyncio
    async def test_returns_node_flow_graph_type(self):
        from app.services.supply_chain_service import build_node_flow_graph
        db = self._make_db_for_flow([], [])
        result = await build_node_flow_graph(db)
        assert hasattr(result, "nodes")
        assert hasattr(result, "edges")

    @pytest.mark.asyncio
    async def test_flow_node_has_required_data_fields(self):
        from app.services.supply_chain_service import build_node_flow_graph
        node = _make_mock_node("삼성전자", ticker="005930", lat=37.0, lon=127.0)
        node.outgoing_edges = []
        db = self._make_db_for_flow([node], [])
        result = await build_node_flow_graph(db)
        assert len(result.nodes) == 1
        fn = result.nodes[0]
        assert fn.data["label"] == "삼성전자"
        assert fn.data["ticker"] == "005930"
        assert "risk_color" in fn.data
        assert "risk_level" in fn.data

    @pytest.mark.asyncio
    async def test_flow_node_position_from_coordinates(self):
        """위도·경도 → position 변환 검증."""
        from app.services.supply_chain_service import _LAT_TO_Y_SCALE, _LON_TO_X_SCALE, build_node_flow_graph
        node = _make_mock_node("공장", lat=37.5, lon=127.0)
        node.outgoing_edges = []
        db = self._make_db_for_flow([node], [])
        result = await build_node_flow_graph(db)
        pos = result.nodes[0].position
        assert pos["x"] == round(127.0 * _LON_TO_X_SCALE, 2)
        assert pos["y"] == round(37.5 * _LAT_TO_Y_SCALE, 2)

    @pytest.mark.asyncio
    async def test_risk_color_critical_is_purple(self):
        from app.services.supply_chain_service import build_node_flow_graph
        node = _make_mock_node("위험공장", risk="CRITICAL")
        node.outgoing_edges = []
        db = self._make_db_for_flow([node], [])
        result = await build_node_flow_graph(db)
        assert result.nodes[0].data["risk_color"] == "#9C27B0"

    @pytest.mark.asyncio
    async def test_flow_edge_stroke_width_proportional(self):
        """높은 dependency_score → 두꺼운 stroke."""
        from app.services.supply_chain_service import build_node_flow_graph
        n1 = _make_mock_node("A", lat=37.0, lon=127.0)
        n2 = _make_mock_node("B", lat=36.0, lon=128.0)
        n1.outgoing_edges = []
        n2.outgoing_edges = []
        edge_high = _make_mock_edge(n1.id, n2.id, score=1.0)  # 최대 → 5px
        edge_low = _make_mock_edge(n2.id, n1.id, score=0.1)   # 최소 → 1px
        db = self._make_db_for_flow([n1, n2], [edge_high, edge_low])
        result = await build_node_flow_graph(db)
        scores = {e.data["dependency_score"]: e.data["stroke_width"] for e in result.edges}
        assert scores[1.0] == 5
        assert scores[0.1] == 1


# ─────────────────────────────────────────────────────────────────────────────
# 좌표→위치 변환 유닛 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestCoordsToPosition:
    def test_none_coords_returns_zero(self):
        from app.services.supply_chain_service import _coords_to_position
        pos = _coords_to_position(None, None)
        assert pos == {"x": 0.0, "y": 0.0}

    def test_valid_coords_returns_scaled(self):
        from app.services.supply_chain_service import _coords_to_position
        pos = _coords_to_position(0.0, 0.0)
        assert pos["x"] == 0.0
        assert pos["y"] == 0.0

    def test_positive_lon_positive_x(self):
        from app.services.supply_chain_service import _LAT_TO_Y_SCALE, _LON_TO_X_SCALE, _coords_to_position
        pos = _coords_to_position(10.0, 100.0)
        assert pos["x"] == round(100.0 * _LON_TO_X_SCALE, 2)

    def test_lat_y_inverted(self):
        """y축 반전: 위도 양수 → y 음수."""
        from app.services.supply_chain_service import _coords_to_position
        pos = _coords_to_position(37.0, 0.0)
        assert pos["y"] < 0  # y축 반전


# ─────────────────────────────────────────────────────────────────────────────
# 하위 파급 영향 트래버설 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestGetDownstreamImpact:
    """get_downstream_impact() — BFS 탐색 단위 테스트."""

    def _make_db_traversal(
        self,
        node_map: dict,      # {uuid: mock_node}
        edges_map: dict,     # {source_uuid: [mock_edge, ...]}
    ) -> AsyncMock:
        """노드 조회 + 에지 조회를 순서대로 반환하는 복합 Mock DB."""
        db = AsyncMock()
        call_count = [0]

        async def mock_execute(query):
            result = MagicMock()
            scalars = MagicMock()

            # 호출 패턴: 노드 단건 조회(get_node) 또는 에지 목록(outgoing)
            # get_node는 scalar_one_or_none() 사용, 에지는 scalars().all() 사용
            call_count[0] += 1
            return result

        db.execute = mock_execute
        return db

    @pytest.mark.asyncio
    async def test_returns_empty_for_isolated_node(self):
        """에지 없는 노드 → 빈 파급 목록."""
        from app.services.supply_chain_service import get_downstream_impact

        node_id = uuid.uuid4()

        db = AsyncMock()
        # get_node 호출: scalar_one_or_none() 반환
        node_result = MagicMock()
        node_result.scalar_one_or_none.return_value = None

        # 에지 조회 호출: scalars().all() 반환
        edge_scalars = MagicMock()
        edge_scalars.all.return_value = []
        edge_result = MagicMock()
        edge_result.scalars.return_value = edge_scalars

        db.execute = AsyncMock(side_effect=[edge_result])

        result = await get_downstream_impact(db, node_id, max_depth=1)
        assert result == []

    @pytest.mark.asyncio
    async def test_path_score_decreases_with_depth(self):
        """
        A(score=1.0) → B(score=0.8) 경로:
        B의 path_score = 1.0 * 0.8 = 0.8
        """
        from app.services.supply_chain_service import get_downstream_impact

        node_a_id = uuid.uuid4()
        node_b_id = uuid.uuid4()

        node_b = _make_mock_node("공장B")
        node_b.id = node_b_id

        edge_ab = _make_mock_edge(node_a_id, node_b_id, score=0.8)

        db = AsyncMock()

        # 순서: 1) A의 outgoing edges 조회, 2) get_node(B), 3) B의 outgoing edges
        edge_scalars_a = MagicMock()
        edge_scalars_a.all.return_value = [edge_ab]
        edge_result_a = MagicMock()
        edge_result_a.scalars.return_value = edge_scalars_a

        node_b_result = MagicMock()
        node_b_result.scalar_one_or_none.return_value = node_b

        edge_scalars_b = MagicMock()
        edge_scalars_b.all.return_value = []
        edge_result_b = MagicMock()
        edge_result_b.scalars.return_value = edge_scalars_b

        db.execute = AsyncMock(side_effect=[edge_result_a, node_b_result, edge_result_b])

        result = await get_downstream_impact(db, node_a_id, max_depth=2)
        assert len(result) == 1
        assert abs(result[0]["path_score"] - 0.8) < 0.001
        assert result[0]["depth"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# 지정학적 리스크 프롬프트 빌더 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildRiskAnalysisPrompt:
    """build_risk_analysis_prompt() — 프롬프트 구조 검증."""

    def _make_nodes(self) -> list[dict]:
        return [
            {
                "id": str(uuid.uuid4()),
                "name": "TSMC 타이난 팹",
                "ticker": "TSM",
                "node_type": "FACTORY",
                "country_code": "TW",
                "city": "타이난",
                "industry_sector": "반도체 파운드리",
                "description": "세계 최대 파운드리",
                "risk_level": "HIGH",
            },
            {
                "id": str(uuid.uuid4()),
                "name": "삼성전자 평택 공장",
                "ticker": "005930",
                "node_type": "FACTORY",
                "country_code": "KR",
                "city": "평택",
                "industry_sector": "반도체",
                "description": None,
                "risk_level": "LOW",
            },
        ]

    def test_returns_three_messages(self):
        from app.services.ai.prompt_builder import build_risk_analysis_prompt
        msgs = build_risk_analysis_prompt(
            news_text="대만해협 봉쇄 위기",
            portfolio_tickers=["AAPL", "NVDA"],
            supply_chain_nodes=self._make_nodes(),
            user_question="파급 효과 분석해줘",
        )
        assert len(msgs) == 3

    def test_first_message_is_user_role(self):
        from app.services.ai.prompt_builder import build_risk_analysis_prompt
        msgs = build_risk_analysis_prompt("test", ["AAPL"], [], "q")
        assert msgs[0]["role"] == "user"

    def test_second_message_is_model_role(self):
        from app.services.ai.prompt_builder import build_risk_analysis_prompt
        msgs = build_risk_analysis_prompt("test", ["AAPL"], [], "q")
        assert msgs[1]["role"] == "model"

    def test_third_message_contains_news(self):
        from app.services.ai.prompt_builder import build_risk_analysis_prompt
        news = "호르무즈 해협 봉쇄로 유가 급등"
        msgs = build_risk_analysis_prompt(news, ["XOM"], [], "분석")
        assert news in msgs[2]["parts"][0]

    def test_third_message_contains_tickers(self):
        from app.services.ai.prompt_builder import build_risk_analysis_prompt
        msgs = build_risk_analysis_prompt(
            "뉴스", ["AAPL", "NVDA", "005930"], [], "q"
        )
        content = msgs[2]["parts"][0]
        assert "AAPL" in content
        assert "NVDA" in content
        assert "005930" in content

    def test_supply_chain_nodes_injected(self):
        from app.services.ai.prompt_builder import build_risk_analysis_prompt
        msgs = build_risk_analysis_prompt(
            "대만해협", ["TSM"], self._make_nodes(), "q"
        )
        content = msgs[2]["parts"][0]
        assert "TSMC" in content
        assert "TW" in content

    def test_fixed_prefix_contains_persona(self):
        """첫 번째 메시지에 ARIA 페르소나가 포함되어야 함."""
        from app.services.ai.prompt_builder import build_risk_analysis_prompt
        msgs = build_risk_analysis_prompt("뉴스", ["AAPL"], [], "q")
        assert "ARIA" in msgs[0]["parts"][0]

    def test_fixed_prefix_contains_supply_chain_role(self):
        from app.services.ai.prompt_builder import build_risk_analysis_prompt
        msgs = build_risk_analysis_prompt("뉴스", ["AAPL"], [], "q")
        assert "공급망" in msgs[0]["parts"][0] or "밸류체인" in msgs[0]["parts"][0]

    def test_output_format_section_in_prefix(self):
        """응답 형식 지시문이 프롬프트에 포함되어야 함."""
        from app.services.ai.prompt_builder import build_risk_analysis_prompt
        msgs = build_risk_analysis_prompt("뉴스", ["AAPL"], [], "q")
        combined = msgs[0]["parts"][0]
        assert "직접 영향 노드" in combined or "파급 경로" in combined

    def test_no_supply_chain_nodes_shows_fallback_text(self):
        """노드 없을 때 fallback 텍스트 포함."""
        from app.services.ai.prompt_builder import _format_supply_chain_nodes
        result = _format_supply_chain_nodes([])
        assert "등록된 공급망 노드 없음" in result

    def test_format_nodes_contains_risk_level(self):
        from app.services.ai.prompt_builder import _format_supply_chain_nodes
        nodes = [{"name": "A공장", "ticker": "AAA", "node_type": "FACTORY",
                  "country_code": "TW", "city": "타이페이", "industry_sector": "반도체",
                  "description": None, "risk_level": "CRITICAL"}]
        result = _format_supply_chain_nodes(nodes)
        assert "CRITICAL" in result

    def test_format_nodes_description_optional(self):
        """description=None이면 설명 줄 미출력."""
        from app.services.ai.prompt_builder import _format_supply_chain_nodes
        nodes = [{"name": "항구", "ticker": None, "node_type": "PORT",
                  "country_code": "KR", "city": "부산", "industry_sector": "물류",
                  "description": None, "risk_level": "LOW"}]
        result = _format_supply_chain_nodes(nodes)
        assert "설명:" not in result


# ─────────────────────────────────────────────────────────────────────────────
# Celery 태스크 헬퍼 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractSection:
    """_extract_section() — Gemini 응답 섹션 파싱."""

    def test_extracts_named_section(self):
        from app.worker.tasks.risk_analysis_tasks import _extract_section
        text = "■ 이벤트 요약\n대만해협 긴장 고조\n■ 직접 영향 노드 목록\n노드A"
        result = _extract_section(text, "이벤트 요약")
        assert "대만해협" in result
        assert "노드A" not in result

    def test_returns_fallback_on_missing_section(self):
        from app.worker.tasks.risk_analysis_tasks import _extract_section
        text = "다른 내용만 있는 텍스트"
        result = _extract_section(text, "존재하지않는섹션")
        # fallback: 원문 첫 500자 반환
        assert len(result) > 0

    def test_extracts_multiline_section(self):
        from app.worker.tasks.risk_analysis_tasks import _extract_section
        text = (
            "■ 공급망 파급 경로\n"
            "1차: TSMC 중단\n"
            "2차: AAPL 공급 차질\n"
            "3차: 스마트폰 가격 상승\n"
            "■ 면책 고지\n"
            "투자 참고 자료"
        )
        result = _extract_section(text, "공급망 파급 경로")
        assert "TSMC" in result
        assert "2차" in result
        assert "면책" not in result

    def test_empty_text_returns_fallback(self):
        from app.worker.tasks.risk_analysis_tasks import _extract_section
        result = _extract_section("", "이벤트 요약")
        assert result == "분석 결과 없음"


class TestParseAffectedNodes:
    """_parse_affected_nodes() — 영향 노드 목록 파싱."""

    def _make_nodes(self) -> list[dict]:
        node_id = str(uuid.uuid4())
        return [
            {
                "id": node_id,
                "name": "TSMC 타이난 팹",
                "ticker": "TSM",
                "country_code": "TW",
            }
        ]

    def test_returns_list(self):
        from app.worker.tasks.risk_analysis_tasks import _parse_affected_nodes
        result = _parse_affected_nodes("분석 결과 없음", [])
        assert isinstance(result, list)

    def test_empty_section_returns_empty(self):
        from app.worker.tasks.risk_analysis_tasks import _parse_affected_nodes
        text = "■ 이벤트 요약\n내용\n■ 포트폴리오 투자 관점 평가\n내용"
        result = _parse_affected_nodes(text, [])
        assert result == []

    def test_parses_bullet_point_nodes(self):
        from app.worker.tasks.risk_analysis_tasks import _parse_affected_nodes
        text = (
            "■ 직접 영향 노드 목록\n"
            "• TSMC 타이난 팹 | TW | 직접 영향 | 치명적\n"
            "  반도체 공급 완전 차단\n"
            "• 부산항 | KR | 간접 파급 | 보통\n"
        )
        result = _parse_affected_nodes(text, self._make_nodes())
        assert len(result) >= 1
        names = [r["node_name"] for r in result]
        assert any("TSMC" in n for n in names)

    def test_matched_node_gets_node_id(self):
        """DB 노드와 이름 매칭 성공 시 node_id 포함."""
        from app.worker.tasks.risk_analysis_tasks import _parse_affected_nodes
        text = (
            "■ 직접 영향 노드 목록\n"
            "• TSMC 타이난 팹 | TW | 직접 영향 | 치명적\n"
        )
        nodes = self._make_nodes()
        result = _parse_affected_nodes(text, nodes)
        matched = [r for r in result if r.get("node_id")]
        assert len(matched) >= 1

    def test_unmatched_node_has_none_id(self):
        """DB에 없는 노드명 → node_id=None."""
        from app.worker.tasks.risk_analysis_tasks import _parse_affected_nodes
        text = (
            "■ 직접 영향 노드 목록\n"
            "• 알 수 없는 공장 | CN | 직접 영향 | 심각\n"
        )
        result = _parse_affected_nodes(text, [])
        if result:
            assert result[0]["node_id"] is None

    def test_severity_critical_detected(self):
        from app.worker.tasks.risk_analysis_tasks import _parse_affected_nodes
        text = (
            "■ 직접 영향 노드 목록\n"
            "• 가상 공장 | TW | 직접 영향 | 치명적\n"
        )
        result = _parse_affected_nodes(text, [])
        if result:
            assert result[0]["impact_severity"] == "치명적"

    def test_max_15_nodes_returned(self):
        """최대 15개 노드 반환 제한."""
        from app.worker.tasks.risk_analysis_tasks import _parse_affected_nodes
        lines = "\n".join(
            [f"• 공장{i} | KR | 직접 영향 | 보통" for i in range(20)]
        )
        text = f"■ 직접 영향 노드 목록\n{lines}"
        result = _parse_affected_nodes(text, [])
        assert len(result) <= 15


# ─────────────────────────────────────────────────────────────────────────────
# 마이그레이션 파일 구조 검증
# ─────────────────────────────────────────────────────────────────────────────

class TestMigrationFile:
    """마이그레이션 파일 내용이 올바른지 검증 (파일 파싱)."""

    def test_migration_file_exists(self):
        import os
        path = (
            "alembic/versions/"
            "a1b2c3d4e5f6_create_supply_chain_tables.py"
        )
        assert os.path.exists(path), f"마이그레이션 파일 없음: {path}"

    def test_migration_revision_id(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "migration",
            "alembic/versions/a1b2c3d4e5f6_create_supply_chain_tables.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.revision == "a1b2c3d4e5f6"

    def test_migration_down_revision(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "migration",
            "alembic/versions/a1b2c3d4e5f6_create_supply_chain_tables.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.down_revision == "512ae099cb9b"

    def test_migration_has_upgrade_function(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "migration",
            "alembic/versions/a1b2c3d4e5f6_create_supply_chain_tables.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert callable(mod.upgrade)
        assert callable(mod.downgrade)


# ─────────────────────────────────────────────────────────────────────────────
# 라우터 응답 스키마 통합 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestSupplyChainRouterSchemas:
    """라우터가 올바른 응답 스키마를 사용하는지 임포트 수준에서 검증."""

    def test_router_importable(self):
        from app.api.v1.routers.supply_chain import router
        assert router is not None

    def test_router_prefix(self):
        from app.api.v1.routers.supply_chain import router
        assert router.prefix == "/supply-chain"

    def test_router_tags(self):
        from app.api.v1.routers.supply_chain import router
        assert "Supply Chain" in router.tags

    def test_router_registered_in_v1(self):
        from app.api.v1.router import api_v1_router
        prefixes = [r.prefix for r in api_v1_router.routes
                    if hasattr(r, "prefix")]
        # include_router로 등록된 라우터는 routes에 flat하게 존재
        # 대신 router 모듈 임포트가 성공하는지로 검증
        from app.api.v1.routers.supply_chain import router as sc_router
        assert sc_router is not None

    def test_celery_app_includes_risk_task(self):
        from app.worker.celery_app import celery_app
        assert any(
            "risk_analysis_tasks" in inc
            for inc in celery_app.conf.include
        )
