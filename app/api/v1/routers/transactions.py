"""
Transaction 라우터 — 거래 내역 수동 기록

POST /api/v1/portfolios/{id}/transactions     — 거래 내역 수동 등록
GET  /api/v1/portfolios/{id}/transactions     — 거래 내역 조회

핵심 제약: 이 엔드포인트는 실제 매수/매도를 실행하지 않음.
이미 완료된 거래를 소급하여 기록하는 분석 지원 기능.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_active_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.transaction import TransactionCreate, TransactionResponse
from app.services.portfolio_service import add_transaction, list_transactions

router = APIRouter(
    prefix="/portfolios/{portfolio_id}/transactions",
    tags=["Transactions"],
)


@router.post(
    "",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="거래 내역 수동 등록",
    description=(
        "실제 매수/매도 실행이 아닌, 이미 완료된 거래를 기록합니다. "
        "BUY 등록 시 Holdings 수량과 평균 단가가 자동 업데이트됩니다. "
        "SELL 등록 시 Holdings 수량이 차감됩니다."
    ),
)
async def record_transaction(
    portfolio_id: uuid.UUID,
    req: TransactionCreate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TransactionResponse:
    return await add_transaction(db, portfolio_id, current_user, req)


@router.get(
    "",
    response_model=list[TransactionResponse],
    summary="거래 내역 목록 조회",
)
async def list_all(
    portfolio_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[TransactionResponse]:
    return await list_transactions(db, portfolio_id, current_user)
