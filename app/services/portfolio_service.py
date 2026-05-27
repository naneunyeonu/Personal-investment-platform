"""
Portfolio / Holding / Transaction 서비스 레이어

핵심 제약: 이 플랫폼은 실제 주문 체결을 수행하지 않음.
모든 데이터는 사용자가 수동으로 입력하며 분석 목적으로만 사용됨.
"""

import uuid
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.portfolio import HoldingCreate, HoldingUpdate, PortfolioCreate, PortfolioUpdate
from app.schemas.transaction import TransactionCreate


# ─────────────────────────────────────────────────────────────────────────────
# 공통 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

async def _get_portfolio_or_404(
    db: AsyncSession, portfolio_id: uuid.UUID, owner: User
) -> Portfolio:
    """소유 포트폴리오 조회. 없거나 타인 소유면 404."""
    result = await db.execute(
        select(Portfolio).where(
            Portfolio.id == portfolio_id,
            Portfolio.owner_id == owner.id,
            Portfolio.is_active == True,  # noqa: E712
        )
    )
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Portfolio not found",
        )
    return portfolio


# ─────────────────────────────────────────────────────────────────────────────
# Portfolio CRUD
# ─────────────────────────────────────────────────────────────────────────────

async def create_portfolio(
    db: AsyncSession, owner: User, req: PortfolioCreate
) -> Portfolio:
    portfolio = Portfolio(
        owner_id=owner.id,
        name=req.name,
        description=req.description,
        base_currency=req.base_currency.value,
    )
    db.add(portfolio)
    await db.flush()
    await db.refresh(portfolio)
    return portfolio


async def list_portfolios(db: AsyncSession, owner: User) -> list[Portfolio]:
    result = await db.execute(
        select(Portfolio).where(
            Portfolio.owner_id == owner.id,
            Portfolio.is_active == True,  # noqa: E712
        )
    )
    return list(result.scalars().all())


async def get_portfolio(
    db: AsyncSession, portfolio_id: uuid.UUID, owner: User
) -> Portfolio:
    return await _get_portfolio_or_404(db, portfolio_id, owner)


async def update_portfolio(
    db: AsyncSession,
    portfolio_id: uuid.UUID,
    owner: User,
    req: PortfolioUpdate,
) -> Portfolio:
    portfolio = await _get_portfolio_or_404(db, portfolio_id, owner)
    updates = req.model_dump(exclude_unset=True)
    for field, value in updates.items():
        if field == "base_currency" and value is not None:
            setattr(portfolio, field, value.value)
        else:
            setattr(portfolio, field, value)
    await db.flush()
    await db.refresh(portfolio)
    return portfolio


async def delete_portfolio(
    db: AsyncSession, portfolio_id: uuid.UUID, owner: User
) -> None:
    """소프트 삭제 (is_active=False)"""
    portfolio = await _get_portfolio_or_404(db, portfolio_id, owner)
    portfolio.is_active = False
    await db.flush()


# ─────────────────────────────────────────────────────────────────────────────
# Holding CRUD  (수동 입력 보유 종목)
# ─────────────────────────────────────────────────────────────────────────────

async def add_holding(
    db: AsyncSession,
    portfolio_id: uuid.UUID,
    owner: User,
    req: HoldingCreate,
) -> Holding:
    """
    포트폴리오에 보유 종목을 수동 등록.
    동일 ticker가 있으면 수량/평균단가 가중 평균 업데이트.
    """
    await _get_portfolio_or_404(db, portfolio_id, owner)

    existing = await db.execute(
        select(Holding).where(
            Holding.portfolio_id == portfolio_id,
            Holding.ticker == req.ticker,
        )
    )
    holding = existing.scalar_one_or_none()

    if holding:
        # 수량 가중 평균 단가 재계산
        old_qty = holding.quantity
        new_qty = req.quantity
        total_qty = old_qty + new_qty
        holding.average_cost = (
            (holding.average_cost * old_qty + req.average_cost * new_qty)
            / total_qty
        )
        holding.quantity = total_qty
        # 환율도 동일한 방식으로 가중 평균
        holding.execution_exchange_rate = (  # type: ignore[attr-defined]
            (getattr(holding, "execution_exchange_rate", Decimal("1")) * old_qty
             + req.execution_exchange_rate * new_qty)
            / total_qty
        )
    else:
        holding = Holding(
            portfolio_id=portfolio_id,
            ticker=req.ticker,
            asset_class=req.asset_class,
            market=req.market,
            quantity=req.quantity,
            average_cost=req.average_cost,
            currency_code=req.currency_code,
        )
        db.add(holding)

    await db.flush()
    await db.refresh(holding)
    return holding


async def list_holdings(
    db: AsyncSession, portfolio_id: uuid.UUID, owner: User
) -> list[Holding]:
    await _get_portfolio_or_404(db, portfolio_id, owner)
    result = await db.execute(
        select(Holding).where(Holding.portfolio_id == portfolio_id)
    )
    return list(result.scalars().all())


async def update_holding(
    db: AsyncSession,
    portfolio_id: uuid.UUID,
    holding_id: uuid.UUID,
    owner: User,
    req: HoldingUpdate,
) -> Holding:
    await _get_portfolio_or_404(db, portfolio_id, owner)
    result = await db.execute(
        select(Holding).where(
            Holding.id == holding_id,
            Holding.portfolio_id == portfolio_id,
        )
    )
    holding = result.scalar_one_or_none()
    if holding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Holding not found")

    updates = req.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(holding, field, value)
    await db.flush()
    await db.refresh(holding)
    return holding


async def delete_holding(
    db: AsyncSession,
    portfolio_id: uuid.UUID,
    holding_id: uuid.UUID,
    owner: User,
) -> None:
    await _get_portfolio_or_404(db, portfolio_id, owner)
    result = await db.execute(
        select(Holding).where(
            Holding.id == holding_id,
            Holding.portfolio_id == portfolio_id,
        )
    )
    holding = result.scalar_one_or_none()
    if holding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Holding not found")
    await db.delete(holding)
    await db.flush()


# ─────────────────────────────────────────────────────────────────────────────
# Transaction  (수동 거래 기록)
# ─────────────────────────────────────────────────────────────────────────────

async def add_transaction(
    db: AsyncSession,
    portfolio_id: uuid.UUID,
    owner: User,
    req: TransactionCreate,
) -> Transaction:
    """
    이미 완료된 거래를 소급 기록 (실제 체결 아님).
    BUY 기록 시 Holding 수량/평균단가도 자동 업데이트.
    SELL 기록 시 수량 차감 (보유량 초과 시 400 반환).
    """
    await _get_portfolio_or_404(db, portfolio_id, owner)

    tx = Transaction(
        portfolio_id=portfolio_id,
        user_id=owner.id,
        ticker=req.ticker,
        asset_class=req.asset_class,
        market=req.market,
        transaction_type=req.transaction_type,
        quantity=req.quantity,
        execution_price=req.execution_price,
        currency_code=req.currency_code,
        execution_exchange_rate=req.execution_exchange_rate,
        commission=req.commission,
        commission_currency=req.commission_currency,
        notes=req.notes,
    )
    db.add(tx)

    # Holding 자동 동기화
    await _sync_holding_from_transaction(db, portfolio_id, req)

    await db.flush()
    await db.refresh(tx)
    return tx


async def _sync_holding_from_transaction(
    db: AsyncSession,
    portfolio_id: uuid.UUID,
    req: TransactionCreate,
) -> None:
    from app.core.enums import TransactionType

    result = await db.execute(
        select(Holding).where(
            Holding.portfolio_id == portfolio_id,
            Holding.ticker == req.ticker,
        )
    )
    holding = result.scalar_one_or_none()

    if req.transaction_type == TransactionType.BUY:
        if holding:
            old_qty = holding.quantity
            new_qty = req.quantity
            total_qty = old_qty + new_qty
            holding.average_cost = (
                (holding.average_cost * old_qty + req.execution_price * new_qty)
                / total_qty
            )
            holding.quantity = total_qty
        else:
            holding = Holding(
                portfolio_id=portfolio_id,
                ticker=req.ticker,
                asset_class=req.asset_class,
                market=req.market,
                quantity=req.quantity,
                average_cost=req.execution_price,
                currency_code=req.currency_code,
            )
            db.add(holding)

    elif req.transaction_type == TransactionType.SELL:
        if holding is None or holding.quantity < req.quantity:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient holding quantity for {req.ticker}",
            )
        holding.quantity -= req.quantity
        if holding.quantity == Decimal("0"):
            await db.delete(holding)


async def list_transactions(
    db: AsyncSession, portfolio_id: uuid.UUID, owner: User
) -> list[Transaction]:
    await _get_portfolio_or_404(db, portfolio_id, owner)
    result = await db.execute(
        select(Transaction)
        .where(Transaction.portfolio_id == portfolio_id)
        .order_by(Transaction.created_at.desc())
    )
    return list(result.scalars().all())
