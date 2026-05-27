// ── 포트폴리오 관련 타입 ─────────────────────────────────────────────────────

export type CurrencyCode = 'KRW' | 'USD' | 'JPY' | 'EUR' | 'HKD'
export type AssetClass   = 'STOCK' | 'ETF' | 'BOND' | 'CRYPTO' | 'CASH'
export type MarketType   = 'KRX' | 'NASDAQ' | 'NYSE' | 'AMEX' | 'OTHER'
export type TransactionType = 'BUY' | 'SELL' | 'DIVIDEND'

// ── Portfolio ─────────────────────────────────────────────────────────────

export interface Portfolio {
  id: string
  name: string
  description: string | null
  base_currency: CurrencyCode
  is_active: boolean
  created_at: string
}

export interface PortfolioCreate {
  name: string
  description?: string
  base_currency: CurrencyCode
}

// ── Holding ───────────────────────────────────────────────────────────────

export interface Holding {
  id: string
  portfolio_id: string
  ticker: string
  asset_class: AssetClass
  market: MarketType
  quantity: string       // Decimal → string
  average_cost: string
  currency_code: CurrencyCode
  created_at: string
}

export interface HoldingCreate {
  ticker: string
  asset_class: AssetClass
  market: MarketType
  quantity: string
  average_cost: string
  currency_code: CurrencyCode
  execution_exchange_rate: string
}

// ── Valuation (현재가 반영 수익률) ─────────────────────────────────────────

export interface HoldingValuation {
  ticker: string
  quantity: number
  average_cost: number
  current_price: number
  currency_code: CurrencyCode
  current_price_krw: number
  cost_krw: number
  gain_loss_krw: number
  gain_loss_pct: number
  price_contribution_krw: number
  fx_contribution_krw: number
}

export interface PortfolioValuation {
  portfolio_id: string
  portfolio_name: string
  base_currency: CurrencyCode
  usd_krw_rate: number
  rate_source: string
  total_cost_krw: number
  total_value_krw: number
  total_return_pct: number
  price_contribution_krw: number
  fx_contribution_krw: number
  holdings: HoldingValuation[]
}
