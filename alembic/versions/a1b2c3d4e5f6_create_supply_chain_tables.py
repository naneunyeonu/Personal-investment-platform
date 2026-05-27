"""create_supply_chain_tables

Revision ID: a1b2c3d4e5f6
Revises: 512ae099cb9b
Create Date: 2026-05-27 18:00:00.000000

공급망(밸류체인) 시각화 테이블 생성 (architecture_plan.md §7.1)

테이블 생성 순서:
  supply_chain_nodes  — 기업/공장/항구/물류 노드 (위치 + 리스크)
  supply_chain_edges  — 노드 간 의존 관계 + 물류 흐름

ENUM 타입:
  supply_chain_node_type  — COMPANY / FACTORY / PORT / LOGISTICS_HUB /
                            RAW_MATERIAL_SITE / DISTRIBUTION_CENTER
  supply_chain_relation_type — SUPPLIES / MANUFACTURES_FOR /
                                DISTRIBUTES_TO / DEPENDS_ON
  node_risk_level         — LOW / MEDIUM / HIGH / CRITICAL
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "512ae099cb9b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── ENUM 타입 생성 ────────────────────────────────────────────────────
    op.execute(
        "CREATE TYPE supply_chain_node_type AS ENUM ("
        "'COMPANY', 'FACTORY', 'PORT', 'LOGISTICS_HUB', "
        "'RAW_MATERIAL_SITE', 'DISTRIBUTION_CENTER')"
    )
    op.execute(
        "CREATE TYPE supply_chain_relation_type AS ENUM ("
        "'SUPPLIES', 'MANUFACTURES_FOR', 'DISTRIBUTES_TO', 'DEPENDS_ON')"
    )
    op.execute(
        "CREATE TYPE node_risk_level AS ENUM "
        "('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')"
    )

    # ── supply_chain_nodes 테이블 ─────────────────────────────────────────
    op.create_table(
        "supply_chain_nodes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        # 식별 정보
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("ticker", sa.String(20), nullable=True),
        sa.Column(
            "node_type",
            sa.Enum(
                "COMPANY", "FACTORY", "PORT", "LOGISTICS_HUB",
                "RAW_MATERIAL_SITE", "DISTRIBUTION_CENTER",
                name="supply_chain_node_type",
                create_type=False,
            ),
            nullable=False,
        ),
        # 위치 데이터
        sa.Column("country_code", sa.String(3), nullable=False),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("latitude", sa.Float, nullable=True),
        sa.Column("longitude", sa.Float, nullable=True),
        # 산업 분류
        sa.Column("industry_sector", sa.String(100), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        # 지정학적 리스크
        sa.Column(
            "risk_level",
            sa.Enum(
                "LOW", "MEDIUM", "HIGH", "CRITICAL",
                name="node_risk_level",
                create_type=False,
            ),
            nullable=False,
            server_default="LOW",
        ),
        sa.Column("risk_note", sa.Text, nullable=True),
        # 타임스탬프
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # 인덱스
    op.create_index(
        "ix_supply_chain_nodes_ticker",
        "supply_chain_nodes",
        ["ticker"],
    )
    op.create_index(
        "ix_supply_chain_nodes_country_risk",
        "supply_chain_nodes",
        ["country_code", "risk_level"],
    )
    op.create_index(
        "ix_supply_chain_nodes_node_type",
        "supply_chain_nodes",
        ["node_type"],
    )

    # ── supply_chain_edges 테이블 ─────────────────────────────────────────
    op.create_table(
        "supply_chain_edges",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "source_node_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("supply_chain_nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_node_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("supply_chain_nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "relation_type",
            sa.Enum(
                "SUPPLIES", "MANUFACTURES_FOR", "DISTRIBUTES_TO", "DEPENDS_ON",
                name="supply_chain_relation_type",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("dependency_score", sa.Float, nullable=False, server_default="0.5"),
        sa.Column("annual_value_usd", sa.Numeric(precision=20, scale=2), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # 인덱스
    op.create_index(
        "ix_supply_chain_edges_source_node_id",
        "supply_chain_edges",
        ["source_node_id"],
    )
    op.create_index(
        "ix_supply_chain_edges_target_node_id",
        "supply_chain_edges",
        ["target_node_id"],
    )
    op.create_index(
        "ix_supply_chain_edges_source_target",
        "supply_chain_edges",
        ["source_node_id", "target_node_id"],
    )


def downgrade() -> None:
    # 테이블 삭제 (FK 의존 순서: edges → nodes)
    op.drop_index("ix_supply_chain_edges_source_target", table_name="supply_chain_edges")
    op.drop_index("ix_supply_chain_edges_target_node_id", table_name="supply_chain_edges")
    op.drop_index("ix_supply_chain_edges_source_node_id", table_name="supply_chain_edges")
    op.drop_table("supply_chain_edges")

    op.drop_index("ix_supply_chain_nodes_node_type", table_name="supply_chain_nodes")
    op.drop_index("ix_supply_chain_nodes_country_risk", table_name="supply_chain_nodes")
    op.drop_index("ix_supply_chain_nodes_ticker", table_name="supply_chain_nodes")
    op.drop_table("supply_chain_nodes")

    # ENUM 타입 삭제
    op.execute("DROP TYPE IF EXISTS supply_chain_node_type")
    op.execute("DROP TYPE IF EXISTS supply_chain_relation_type")
    op.execute("DROP TYPE IF EXISTS node_risk_level")
