"""
Holdings 라우터 — 수동 보유 종목 관리

POST   /api/v1/portfolios/{id}/holdings           — 종목 수동 등록
GET    /api/v1/portfolios/{id}/holdings           — 보유 종목 목록 조회
PATCH  /api/v1/portfolios/{id}/holdings/{hid}     — 수량/평균단가 수정
DELETE /api/v1/portfolios/{id}/holdings/{hid}     — 종목 삭제

핵심 제약: 실제 주문 체결 없음. 사용자가 보유 내역을 직접 입력.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_active_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.portfolio import HoldingCreate, HoldingResponse, HoldingUpdate
from app.services.portfolio_service import (
    add_holding,
    delete_holding,
    list_holdings,
    update_holding,
)

router = APIRouter(
    prefix="/portfolios/{portfolio_id}/holdings",
    tags=["Holdings"],
)


@router.post(
    "",
    response_model=HoldingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="보유 종목 수동 등록",
    description=(
        "사용자가 보유 중인 종목을 직접 입력합니다. "
        "실제 주문 체결과 무관하며, 분석 목적의 데이터 등록입니다."
    ),
)
async def add(
    portfolio_id: uuid.UUID,
    req: HoldingCreate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HoldingResponse:
    return await add_holding(db, portfolio_id, current_user, req)


@router.get(
    "",
    response_model=list[HoldingResponse],
    summary="보유 종목 목록 조회",
)
async def list_all(
    portfolio_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[HoldingResponse]:
    return await list_holdings(db, portfolio_id, current_user)


@router.patch(
    "/{holding_id}",
    response_model=HoldingResponse,
    summary="보유 종목 수정 (수량/평균단가/환율)",
)
async def update(
    portfolio_id: uuid.UUID,
    holding_id: uuid.UUID,
    req: HoldingUpdate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HoldingResponse:
    return await update_holding(db, portfolio_id, holding_id, current_user, req)


@router.delete(
    "/{holding_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="보유 종목 삭제",
)
async def delete(
    portfolio_id: uuid.UUID,
    holding_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await delete_holding(db, portfolio_id, holding_id, current_user)
