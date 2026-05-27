"""
공급망(밸류체인) 관계형 모델 (architecture_plan.md §7.1)

그래프 구조를 PostgreSQL RDBMS 테이블로 표현:
  SupplyChainNode  — 개별 기업/공장/항구/물류센터 등 위치 노드
  SupplyChainEdge  — 노드 간 의존 관계 및 물류 흐름

프론트엔드 연동:
  - GeoJSON FeatureCollection → Mapbox / Leaflet 지도 레이어
  - Node-Flow JSON → D3.js / React Flow 네트워크 다이어그램

지정학적 리스크 탐지:
  - risk_level 컬럼: 실시간 이벤트 발생 시 CRITICAL로 업데이트
  - risk_note 컬럼: AI 분석 결과 텍스트 저장
  - dependency_score: 에지별 의존도 (0.0~1.0)로 파급 강도 측정
"""

import uuid

from sqlalchemy import Float, ForeignKey, Index, Numeric, String, Text
from sqlalchemy import Enum as PgEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import NodeRiskLevel, SupplyChainNodeType, SupplyChainRelationType
from app.db.base import Base, TimestampMixin


class SupplyChainNode(Base, TimestampMixin):
    """
    공급망 노드 — 기업, 공장, 항구, 물류 허브 등 위치 데이터.

    좌표(latitude, longitude)는 Mapbox/Leaflet GeoJSON Point 생성에 직접 활용.
    ticker 가 있는 노드는 사용자 포트폴리오 보유 종목과 조인 가능.
    """
    __tablename__ = "supply_chain_nodes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # ── 식별 정보 ──────────────────────────────────────────────────────────
    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="노드 표시명 (예: 삼성전자 평택 반도체 공장)",
    )
    ticker: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        index=True,
        comment="상장 기업 티커 (비상장 법인 또는 인프라 노드는 NULL 허용)",
    )
    node_type: Mapped[SupplyChainNodeType] = mapped_column(
        PgEnum(SupplyChainNodeType, name="supply_chain_node_type", create_type=True),
        nullable=False,
        comment="노드 유형: COMPANY / FACTORY / PORT / LOGISTICS_HUB / ...",
    )

    # ── 위치 데이터 (GeoJSON Point 생성용) ────────────────────────────────
    country_code: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        comment="ISO 3166-1 alpha-2 국가 코드 (예: KR, US, CN, TW)",
    )
    city: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="도시명",
    )
    latitude: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="위도 (-90 ~ 90)",
    )
    longitude: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="경도 (-180 ~ 180)",
    )

    # ── 산업/업종 분류 ─────────────────────────────────────────────────────
    industry_sector: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="GICS 기준 섹터 (예: 정보기술, 반도체, 자동차 부품)",
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="노드 상세 설명 (AI 프롬프트 컨텍스트 활용 가능)",
    )

    # ── 지정학적 리스크 ────────────────────────────────────────────────────
    risk_level: Mapped[NodeRiskLevel] = mapped_column(
        PgEnum(NodeRiskLevel, name="node_risk_level", create_type=True),
        nullable=False,
        default=NodeRiskLevel.LOW,
        server_default="LOW",
        comment="현재 지정학적/물리적 위험 수준 (AI 분석으로 업데이트)",
    )
    risk_note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="리스크 요인 자연어 설명 (Gemini AI 분석 결과 저장)",
    )

    # ── 관계 ───────────────────────────────────────────────────────────────
    outgoing_edges: Mapped[list["SupplyChainEdge"]] = relationship(
        "SupplyChainEdge",
        foreign_keys="SupplyChainEdge.source_node_id",
        back_populates="source_node",
        cascade="all, delete-orphan",
    )
    incoming_edges: Mapped[list["SupplyChainEdge"]] = relationship(
        "SupplyChainEdge",
        foreign_keys="SupplyChainEdge.target_node_id",
        back_populates="target_node",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_supply_chain_nodes_country_risk", "country_code", "risk_level"),
        Index("ix_supply_chain_nodes_node_type", "node_type"),
    )

    def __repr__(self) -> str:
        return (
            f"<SupplyChainNode name={self.name!r} ticker={self.ticker} "
            f"type={self.node_type} risk={self.risk_level}>"
        )


class SupplyChainEdge(Base, TimestampMixin):
    """
    공급망 에지 — 노드 간 물류 흐름 및 의존 관계.

    dependency_score (0.0~1.0):
      0.0 = 무관 / 1.0 = 완전 의존
      AI 파급 효과 계산의 가중치로 활용.
      0.7 이상 → 해당 노드 장애 시 상위 노드에 심각한 영향.

    GeoJSON LineString:
      source_node의 좌표 → target_node의 좌표를 연결하여
      프론트엔드 지도에서 물류 흐름 화살표로 시각화.
    """
    __tablename__ = "supply_chain_edges"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # ── 관계 노드 ──────────────────────────────────────────────────────────
    source_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("supply_chain_nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="공급 시작 노드 (예: 대만 TSMC 공장)",
    )
    target_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("supply_chain_nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="공급 수신 노드 (예: 삼성전자 평택 공장)",
    )

    # ── 관계 특성 ──────────────────────────────────────────────────────────
    relation_type: Mapped[SupplyChainRelationType] = mapped_column(
        PgEnum(
            SupplyChainRelationType,
            name="supply_chain_relation_type",
            create_type=True,
        ),
        nullable=False,
        comment="관계 유형: SUPPLIES / MANUFACTURES_FOR / DISTRIBUTES_TO / DEPENDS_ON",
    )
    dependency_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.5,
        comment="의존도 점수 0.0~1.0 (0.7 이상: 고의존)",
    )
    annual_value_usd: Mapped[float | None] = mapped_column(
        Numeric(precision=20, scale=2),
        nullable=True,
        comment="연간 거래 규모 USD (선택 정보, 파급 강도 가중치)",
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="관계 상세 설명",
    )

    # ── 관계 ───────────────────────────────────────────────────────────────
    source_node: Mapped["SupplyChainNode"] = relationship(
        "SupplyChainNode",
        foreign_keys=[source_node_id],
        back_populates="outgoing_edges",
    )
    target_node: Mapped["SupplyChainNode"] = relationship(
        "SupplyChainNode",
        foreign_keys=[target_node_id],
        back_populates="incoming_edges",
    )

    __table_args__ = (
        Index("ix_supply_chain_edges_source_target", "source_node_id", "target_node_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<SupplyChainEdge {self.source_node_id} "
            f"--[{self.relation_type}, score={self.dependency_score}]--> "
            f"{self.target_node_id}>"
        )
