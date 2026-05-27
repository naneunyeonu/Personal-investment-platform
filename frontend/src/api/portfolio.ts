import { api } from './client'
import type {
  Portfolio,
  PortfolioCreate,
  Holding,
  HoldingCreate,
  PortfolioValuation,
} from '../types/portfolio'

// ── Portfolio CRUD ────────────────────────────────────────────────────────

export const listPortfolios = (): Promise<Portfolio[]> =>
  api.get<Portfolio[]>('/portfolios').then(r => r.data)

export const createPortfolio = (data: PortfolioCreate): Promise<Portfolio> =>
  api.post<Portfolio>('/portfolios', data).then(r => r.data)

export const deletePortfolio = (id: string): Promise<void> =>
  api.delete(`/portfolios/${id}`).then(() => undefined)

// ── Holding CRUD ──────────────────────────────────────────────────────────

export const listHoldings = (portfolioId: string): Promise<Holding[]> =>
  api.get<Holding[]>(`/portfolios/${portfolioId}/holdings`).then(r => r.data)

export const addHolding = (portfolioId: string, data: HoldingCreate): Promise<Holding> =>
  api.post<Holding>(`/portfolios/${portfolioId}/holdings`, data).then(r => r.data)

export const deleteHolding = (portfolioId: string, holdingId: string): Promise<void> =>
  api.delete(`/portfolios/${portfolioId}/holdings/${holdingId}`).then(() => undefined)

// ── Valuation (현재가 반영 수익률) ─────────────────────────────────────────

export const getPortfolioValuation = (portfolioId: string): Promise<PortfolioValuation> =>
  api.get<PortfolioValuation>(`/valuation/portfolio/${portfolioId}`).then(r => r.data)
