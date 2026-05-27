from fastapi import APIRouter

from app.api.v1.routers.admin import router as admin_router
from app.api.v1.routers.ai_report import router as ai_report_router
from app.api.v1.routers.auth import router as auth_router
from app.api.v1.routers.holdings import router as holdings_router
from app.api.v1.routers.portfolio import router as portfolio_router
from app.api.v1.routers.supply_chain import router as supply_chain_router
from app.api.v1.routers.transactions import router as transactions_router
from app.api.v1.routers.valuation import router as valuation_router

api_v1_router = APIRouter(prefix="/api/v1")

api_v1_router.include_router(auth_router)
api_v1_router.include_router(admin_router)
api_v1_router.include_router(portfolio_router)
api_v1_router.include_router(holdings_router)
api_v1_router.include_router(transactions_router)
api_v1_router.include_router(valuation_router)
api_v1_router.include_router(ai_report_router)
api_v1_router.include_router(supply_chain_router)
