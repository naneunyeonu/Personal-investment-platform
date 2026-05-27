"""
Portfolio 라우터

POST   /api/v1/portfolios           — 포트폴리오 생성
GET    /api/v1/portfolios           — 내 포트폴리오 목록
GET    /api/v1/portfolios/{id}      — 포트폴리오 상세
PATCH  /api/v1/portfolios/{id}      — 포트폴리오 수정
DELETE /api/v1/portfolios/{id}      — 포트폴리오 소프트 삭제

핵심 제약: 실제 매수/매도 실행 엔드포인트 없음. 분석 서포트 전용.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_active_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.portfolio import PortfolioCreate, PortfolioResponse, PortfolioUpdate
from app.services.portfolio_service import (
    create_portfolio,
    delete_portfolio,
    get_portfolio,
    list_portfolios,
    update_portfolio,
)

router = APIRouter(prefix="/portfolios", tags=["Portfolios"])


@router.post(
    "",
    response_model=PortfolioResponse,
    status_code=status.HTTP_201_CREATED,
    summary="포트폴리오 생성",
)
async def create(
    req: PortfolioCreate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PortfolioResponse:
    return await create_portfolio(db, current_user, req)


@router.get(
    "",
    response_model=list[PortfolioResponse],
    summary="내 포트폴리오 목록 조회",
)
async def list_all(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[PortfolioResponse]:
    return await list_portfolios(db, current_user)


@router.get(
    "/{portfolio_id}",
    response_model=PortfolioResponse,
    summary="포트폴리오 상세 조회",
)
async def get_one(
    portfolio_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PortfolioResponse:
    return await get_portfolio(db, portfolio_id, current_user)


@router.patch(
    "/{portfolio_id}",
    response_model=PortfolioResponse,
    summary="포트폴리오 수정",
)
async def update(
    portfolio_id: uuid.UUID,
    req: PortfolioUpdate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PortfolioResponse:
    return await update_portfolio(db, portfolio_id, current_user, req)


@router.delete(
    "/{portfolio_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="포트폴리오 삭제 (소프트 삭제)",
)
async def delete(
    portfolio_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await delete_portfolio(db, portfolio_id, current_user)
