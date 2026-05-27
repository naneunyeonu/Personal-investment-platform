"""
포트폴리오 가치 평가 수익률 분해 수식 단위 테스트

수익률 분해 공식 검증:
  price_return  = (P1 - P0) / P0
  fx_return     = (E1 - E0) / E0
  total_return  = (1 + price_r) × (1 + fx_r) - 1

  cost_krw      = P0 × Q × E0
  value_krw     = P1 × Q × E1
  unrealized_pnl = value_krw - cost_krw
"""

import uuid
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.adapters.market_data.base import PriceQuote
from app.core.enums import AssetClass, CurrencyCode, MarketType
from app.services.valuation_service import _calc_holding_valuation, _safe_div


def _make_holding(
    ticker: str = "AAPL",
    avg_cost: str = "150.00",
    quantity: str = "10",
    currency: CurrencyCode = CurrencyCode.USD,
    exec_rate: str = "1300.00",
) -> MagicMock:
    h = MagicMock()
    h.id = uuid.uuid4()
    h.ticker = ticker
    h.asset_class = AssetClass.STOCK
    h.market = MarketType.NASDAQ
    h.currency_code = currency
    h.quantity = Decimal(quantity)
    h.average_cost = Decimal(avg_cost)
    h.execution_exchange_rate = Decimal(exec_rate)
    return h


def _make_quote(ticker: str, price: str, currency: str = "USD") -> PriceQuote:
    return PriceQuote(
        ticker=ticker,
        current_price=Decimal(price),
        currency=currency,
        source="test",
    )


class TestSafeDiv:
    def test_normal_division(self):
        assert _safe_div(Decimal("10"), Decimal("4")) == Decimal("2.5")

    def test_zero_denominator(self):
        assert _safe_div(Decimal("10"), Decimal("0")) == Decimal("0")

    def test_zero_numerator(self):
        assert _safe_div(Decimal("0"), Decimal("5")) == Decimal("0")


class TestHoldingValuation:

    def test_usd_stock_price_gain_only(self):
        """USD 주식: 주가 상승, 환율 불변 → fx_return = 0"""
        holding = _make_holding(avg_cost="100.00", quantity="10", exec_rate="1300.00")
        quote = _make_quote("AAPL", "120.00")
        current_usd_krw = Decimal("1300.00")  # 환율 불변

        hv = _calc_holding_valuation(holding, quote, current_usd_krw)

        # 주가 수익률 = (120-100)/100 = 20%
        assert hv.price_return_pct == Decimal("20.0000")
        # 환율 수익률 = (1300-1300)/1300 = 0%
        assert hv.fx_return_pct == Decimal("0.0000")
        # 총 수익률 = (1.2)(1.0) - 1 = 20%
        assert hv.total_return_pct == Decimal("20.0000")
        # 원화 투자원금 = 100 × 10 × 1300 = 1,300,000
        assert hv.cost_krw == Decimal("1300000.00")
        # 현재 원화 평가액 = 120 × 10 × 1300 = 1,560,000
        assert hv.current_value_krw == Decimal("1560000.00")

    def test_usd_stock_fx_gain_only(self):
        """USD 주식: 주가 불변, 환율 상승 → price_return = 0"""
        holding = _make_holding(avg_cost="100.00", quantity="10", exec_rate="1300.00")
        quote = _make_quote("AAPL", "100.00")
        current_usd_krw = Decimal("1430.00")   # 환율 +10%

        hv = _calc_holding_valuation(holding, quote, current_usd_krw)

        # 주가 수익률 = 0%
        assert hv.price_return_pct == Decimal("0.0000")
        # 환율 수익률 = (1430-1300)/1300 ≈ 10%
        assert hv.fx_return_pct == Decimal("10.0000")
        # 총 수익률 = (1.0)(1.1) - 1 = 10%
        assert hv.total_return_pct == Decimal("10.0000")

    def test_usd_stock_compound_return(self):
        """USD 주식: 주가 +20%, 환율 +10% → 복합 수익률 = (1.2)(1.1)-1 = 32%"""
        holding = _make_holding(avg_cost="100.00", quantity="10", exec_rate="1300.00")
        quote = _make_quote("AAPL", "120.00")
        current_usd_krw = Decimal("1430.00")

        hv = _calc_holding_valuation(holding, quote, current_usd_krw)

        assert hv.price_return_pct == Decimal("20.0000")
        assert hv.fx_return_pct == Decimal("10.0000")
        # (1.20)(1.10) - 1 = 0.32 → 32%
        assert hv.total_return_pct == Decimal("32.0000")
        # 원화 평가액 = 120 × 10 × 1430 = 1,716,000
        assert hv.current_value_krw == Decimal("1716000.00")

    def test_krw_stock_no_fx(self):
        """KRW 주식: execution_exchange_rate = 1, fx_return 항상 0"""
        holding = _make_holding(
            ticker="005930",
            avg_cost="70000",
            quantity="5",
            currency=CurrencyCode.KRW,
            exec_rate="1.0",
        )
        quote = _make_quote("005930", "77000", currency="KRW")
        current_usd_krw = Decimal("1350.00")

        hv = _calc_holding_valuation(holding, quote, current_usd_krw)

        # KRW 자산 — 환율은 1.0 고정
        assert hv.fx_return_pct == Decimal("0.0000")
        # 주가 수익률 = (77000-70000)/70000 = 10%
        assert hv.price_return_pct == Decimal("10.0000")
        assert hv.total_return_pct == Decimal("10.0000")
        # 원화 평가액 = 77000 × 5 × 1 = 385,000
        assert hv.current_value_krw == Decimal("385000.00")

    def test_price_fetch_failed(self):
        """현재가 조회 실패 시 수익률 0, price_fetch_failed=True"""
        holding = _make_holding(avg_cost="100.00", exec_rate="1300.00")
        current_usd_krw = Decimal("1300.00")

        hv = _calc_holding_valuation(holding, quote=None, current_usd_krw=current_usd_krw)

        assert hv.price_fetch_failed is True
        assert hv.price_return_pct == Decimal("0.0000")
        assert hv.total_return_pct == Decimal("0.0000")

    def test_usd_stock_loss(self):
        """USD 주식 손실 케이스: 주가 -20%, 환율 -5%"""
        holding = _make_holding(avg_cost="200.00", quantity="5", exec_rate="1300.00")
        quote = _make_quote("TSLA", "160.00")
        current_usd_krw = Decimal("1235.00")  # 1300 × 0.95

        hv = _calc_holding_valuation(holding, quote, current_usd_krw)

        # 주가 수익률 = (160-200)/200 = -20%
        assert hv.price_return_pct == Decimal("-20.0000")
        # 환율 수익률 = (1235-1300)/1300 = -5%
        assert hv.fx_return_pct == Decimal("-5.0000")
        # 총 수익률 = (0.8)(0.95) - 1 = -24%
        assert hv.total_return_pct == Decimal("-24.0000")
        assert hv.unrealized_pnl_krw < Decimal("0")
