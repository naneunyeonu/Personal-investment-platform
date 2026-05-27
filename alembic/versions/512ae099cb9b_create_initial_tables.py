"""create_initial_tables

Revision ID: 512ae099cb9b
Revises:
Create Date: 2026-05-27 13:10:38.756597

테이블 생성 순서 (FK 의존성):
  users → portfolios → holdings
                     → transactions
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "512ae099cb9b"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── ENUM 타입 먼저 생성 ────────────────────────────────────────────
    op.execute(
        "CREATE TYPE user_role AS ENUM ('ADMIN', 'USER')"
    )
    op.execute(
        "CREATE TYPE asset_class AS ENUM "
        "('STOCK', 'ETF', 'BOND', 'CRYPTO', 'CASH')"
    )
    op.execute(
        "CREATE TYPE market_type AS ENUM "
        "('KRX', 'NASDAQ', 'NYSE', 'AMEX', 'OTHER')"
    )
    op.execute(
        "CREATE TYPE transaction_type AS ENUM "
        "('BUY', 'SELL', 'DIVIDEND')"
    )
    op.execute(
        "CREATE TYPE currency_code AS ENUM "
        "('KRW', 'USD', 'JPY', 'EUR', 'HKD')"
    )

    # ── users ────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("hashed_password", sa.String(256), nullable=False),
        sa.Column("full_name", sa.String(100), nullable=True),
        sa.Column("phone_number", sa.String(20), nullable=True),
        sa.Column(
            "role",
            sa.Enum("ADMIN", "USER", name="user_role", create_type=False),
            nullable=False,
            server_default="USER",
        ),
        # Soft Delete
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "deactivated_by",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="비활성화를 수행한 ADMIN의 user.id",
        ),
        sa.Column("investment_profile", sa.Text(), nullable=True),
        # Timestamps
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
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # ── portfolios ───────────────────────────────────────────────────────
    op.create_table(
        "portfolios",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "base_currency",
            sa.String(3),
            nullable=False,
            server_default="KRW",
            comment="ISO 4217 통화 코드",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("last_optimization_result", sa.Text(), nullable=True),
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
    op.create_index("ix_portfolios_owner_id", "portfolios", ["owner_id"])

    # ── holdings ─────────────────────────────────────────────────────────
    op.create_table(
        "holdings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "portfolio_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("portfolios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column(
            "asset_class",
            sa.Enum(
                "STOCK", "ETF", "BOND", "CRYPTO", "CASH",
                name="asset_class",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "market",
            sa.Enum(
                "KRX", "NASDAQ", "NYSE", "AMEX", "OTHER",
                name="market_type",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "quantity",
            sa.Numeric(precision=18, scale=8),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "average_cost",
            sa.Numeric(precision=18, scale=4),
            nullable=False,
            server_default="0",
            comment="평균 매수 단가 (원래 통화 기준)",
        ),
        sa.Column(
            "currency_code",
            sa.Enum(
                "KRW", "USD", "JPY", "EUR", "HKD",
                name="currency_code",
                create_type=False,
            ),
            nullable=False,
        ),
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
    op.create_index("ix_holdings_portfolio_id", "holdings", ["portfolio_id"])

    # ── transactions ─────────────────────────────────────────────────────
    op.create_table(
        "transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "portfolio_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("portfolios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            comment="감사 추적용",
        ),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column(
            "asset_class",
            sa.Enum(
                "STOCK", "ETF", "BOND", "CRYPTO", "CASH",
                name="asset_class",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "market",
            sa.Enum(
                "KRX", "NASDAQ", "NYSE", "AMEX", "OTHER",
                name="market_type",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "transaction_type",
            sa.Enum(
                "BUY", "SELL", "DIVIDEND",
                name="transaction_type",
                create_type=False,
            ),
            nullable=False,
        ),
        # ── 다중 통화 회계 핵심 컬럼 ────────────────────────────────────
        sa.Column(
            "quantity",
            sa.Numeric(precision=18, scale=8),
            nullable=False,
            comment="체결 수량",
        ),
        sa.Column(
            "execution_price",
            sa.Numeric(precision=18, scale=4),
            nullable=False,
            comment="체결 단가 (currency_code 기준)",
        ),
        sa.Column(
            "currency_code",
            sa.Enum(
                "KRW", "USD", "JPY", "EUR", "HKD",
                name="currency_code",
                create_type=False,
            ),
            nullable=False,
            comment="체결 통화 (ISO 4217)",
        ),
        sa.Column(
            "execution_exchange_rate",
            sa.Numeric(precision=18, scale=6),
            nullable=False,
            comment="체결 시점 환율 (1 USD = N KRW). KRW 자산은 1.0",
        ),
        # ── 수수료 ───────────────────────────────────────────────────────
        sa.Column(
            "commission",
            sa.Numeric(precision=18, scale=4),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "commission_currency",
            sa.Enum(
                "KRW", "USD", "JPY", "EUR", "HKD",
                name="currency_code",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("broker_order_id", sa.String(100), nullable=True, unique=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
    op.create_index(
        "ix_transactions_portfolio_id", "transactions", ["portfolio_id"]
    )
    op.create_index("ix_transactions_user_id", "transactions", ["user_id"])


def downgrade() -> None:
    op.drop_table("transactions")
    op.drop_table("holdings")
    op.drop_table("portfolios")
    op.drop_table("users")

    op.execute("DROP TYPE IF EXISTS currency_code")
    op.execute("DROP TYPE IF EXISTS transaction_type")
    op.execute("DROP TYPE IF EXISTS market_type")
    op.execute("DROP TYPE IF EXISTS asset_class")
    op.execute("DROP TYPE IF EXISTS user_role")
