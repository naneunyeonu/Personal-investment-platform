/**
 * DashboardPage — 포트폴리오 대시보드 (메인 화면)
 *
 * 주요 기능:
 *   1. 포트폴리오 목록 조회 & 선택
 *   2. 포트폴리오 생성 (수동 입력)
 *   3. 보유 종목 수동 등록
 *   4. 백엔드 시장 데이터 API → 현재가 반영 복합 수익률 표시
 *
 * 이 플랫폼은 실제 주식 매수/매도 실행 기능을 제공하지 않습니다.
 * 사용자가 직접 보유 내역을 입력하면 시장 데이터를 조회하여 분석만 지원합니다.
 */

import { useState, useEffect, type FormEvent } from 'react'
import { useAuth } from '../context/AuthContext'
import {
  listPortfolios,
  createPortfolio,
  getPortfolioValuation,
  addHolding,
} from '../api/portfolio'
import type { Portfolio, HoldingCreate } from '../types/portfolio'
import type { PortfolioValuation } from '../types/portfolio'
import PortfolioStats from '../components/portfolio/PortfolioStats'
import HoldingSummaryCard from '../components/portfolio/HoldingSummaryCard'

// ── 보유 종목 등록 폼 ─────────────────────────────────────────────────────

function AddHoldingForm({
  portfolioId,
  onAdded,
}: {
  portfolioId: string
  onAdded: () => void
}) {
  const INIT: HoldingCreate = {
    ticker: '', asset_class: 'STOCK', market: 'NASDAQ',
    quantity: '', average_cost: '', currency_code: 'USD',
    execution_exchange_rate: '1380',
  }
  const [form, setForm]   = useState<HoldingCreate>(INIT)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState<string | null>(null)

  const set = (k: keyof HoldingCreate, v: string) =>
    setForm(prev => ({ ...prev, [k]: v }))

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setLoading(true); setError(null)
    try {
      await addHolding(portfolioId, form)
      setForm(INIT)
      onAdded()
    } catch {
      setError('종목 등록에 실패했습니다.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={handleSubmit}
          className="bg-slate-800 border border-slate-700 rounded-xl p-5 space-y-4">
      <h3 className="font-semibold text-white">보유 종목 수동 등록</h3>
      <p className="text-xs text-slate-500">
        실제 매수/매도 기능이 아닙니다. 보유 중인 종목 정보를 직접 입력하면 시장 데이터를 조회하여 분석을 제공합니다.
      </p>

      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        {/* 티커 */}
        <div>
          <label className="text-xs text-slate-400 mb-1 block">티커 *</label>
          <input required value={form.ticker} onChange={e => set('ticker', e.target.value.toUpperCase())}
            placeholder="AAPL"
            className="w-full px-3 py-2 rounded-lg bg-slate-700 border border-slate-600 text-white text-sm
                       focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>

        {/* 수량 */}
        <div>
          <label className="text-xs text-slate-400 mb-1 block">수량 *</label>
          <input required type="number" step="any" min="0" value={form.quantity}
            onChange={e => set('quantity', e.target.value)}
            placeholder="10"
            className="w-full px-3 py-2 rounded-lg bg-slate-700 border border-slate-600 text-white text-sm
                       focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>

        {/* 평단가 */}
        <div>
          <label className="text-xs text-slate-400 mb-1 block">평균 매수 단가 *</label>
          <input required type="number" step="any" min="0" value={form.average_cost}
            onChange={e => set('average_cost', e.target.value)}
            placeholder="150.00"
            className="w-full px-3 py-2 rounded-lg bg-slate-700 border border-slate-600 text-white text-sm
                       focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>

        {/* 통화 */}
        <div>
          <label className="text-xs text-slate-400 mb-1 block">통화</label>
          <select value={form.currency_code} onChange={e => set('currency_code', e.target.value as HoldingCreate['currency_code'])}
            className="w-full px-3 py-2 rounded-lg bg-slate-700 border border-slate-600 text-white text-sm
                       focus:outline-none focus:ring-2 focus:ring-blue-500">
            {['USD', 'KRW', 'JPY', 'EUR', 'HKD'].map(c => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </div>

        {/* 매수 당시 환율 */}
        <div>
          <label className="text-xs text-slate-400 mb-1 block">매수 당시 환율 (1 USD = ? KRW)</label>
          <input required type="number" step="any" min="0" value={form.execution_exchange_rate}
            onChange={e => set('execution_exchange_rate', e.target.value)}
            placeholder="1380"
            className="w-full px-3 py-2 rounded-lg bg-slate-700 border border-slate-600 text-white text-sm
                       focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>

        {/* 시장 */}
        <div>
          <label className="text-xs text-slate-400 mb-1 block">거래 시장</label>
          <select value={form.market} onChange={e => set('market', e.target.value as HoldingCreate['market'])}
            className="w-full px-3 py-2 rounded-lg bg-slate-700 border border-slate-600 text-white text-sm
                       focus:outline-none focus:ring-2 focus:ring-blue-500">
            {['NASDAQ', 'NYSE', 'AMEX', 'KRX', 'OTHER'].map(m => (
              <option key={m}>{m}</option>
            ))}
          </select>
        </div>
      </div>

      {error && <p className="text-red-400 text-sm">{error}</p>}

      <button type="submit" disabled={loading}
        className="px-5 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:opacity-60
                   text-white text-sm font-semibold transition-colors">
        {loading ? '등록 중…' : '종목 등록'}
      </button>
    </form>
  )
}

// ── 메인 페이지 ───────────────────────────────────────────────────────────

export default function DashboardPage() {
  const { user } = useAuth()

  const [portfolios, setPortfolios] = useState<Portfolio[]>([])
  const [selected,   setSelected]   = useState<string | null>(null)
  const [valuation,  setValuation]  = useState<PortfolioValuation | null>(null)
  const [loadingVal, setLoadingVal] = useState(false)
  const [newName,    setNewName]    = useState('')
  const [creating,   setCreating]   = useState(false)
  const [showAddHolding, setShowAddHolding] = useState(false)

  // 포트폴리오 목록 로드
  const fetchPortfolios = async () => {
    try {
      const list = await listPortfolios()
      setPortfolios(list)
      if (!selected && list.length > 0) setSelected(list[0].id)
    } catch {
      // 인증 오류는 axios 인터셉터가 처리
    }
  }

  useEffect(() => { fetchPortfolios() }, [])  // eslint-disable-line

  // 선택 포트폴리오 평가 로드
  useEffect(() => {
    if (!selected) return
    setLoadingVal(true)
    setValuation(null)
    getPortfolioValuation(selected)
      .then(setValuation)
      .catch(() => {/* 데이터 없거나 백엔드 미연결 */})
      .finally(() => setLoadingVal(false))
  }, [selected])

  const handleCreatePortfolio = async (e: FormEvent) => {
    e.preventDefault()
    if (!newName.trim()) return
    setCreating(true)
    try {
      const created = await createPortfolio({ name: newName, base_currency: 'KRW' })
      setNewName('')
      setPortfolios(prev => [...prev, created])
      setSelected(created.id)
    } finally {
      setCreating(false)
    }
  }

  const selectedPortfolio = portfolios.find(p => p.id === selected)

  return (
    <div className="space-y-8">

      {/* 헤더 */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">
            안녕하세요, {user?.full_name || user?.email?.split('@')[0]}님 👋
          </h1>
          <p className="text-slate-400 text-sm mt-1">
            보유 자산을 직접 등록하고 AI 분석 리포트를 확인하세요.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">

        {/* 왼쪽: 포트폴리오 목록 */}
        <div className="lg:col-span-1 space-y-4">

          <div className="bg-slate-800 border border-slate-700 rounded-xl p-4">
            <h2 className="font-semibold text-white text-sm mb-3">내 포트폴리오</h2>

            <div className="space-y-1">
              {portfolios.map(p => (
                <button
                  key={p.id}
                  onClick={() => setSelected(p.id)}
                  className={`w-full text-left px-3 py-2.5 rounded-lg text-sm transition-colors ${
                    selected === p.id
                      ? 'bg-blue-600/20 border border-blue-500/40 text-blue-300'
                      : 'text-slate-300 hover:bg-slate-700'
                  }`}
                >
                  {p.name}
                </button>
              ))}

              {portfolios.length === 0 && (
                <p className="text-slate-500 text-xs text-center py-4">
                  포트폴리오가 없습니다
                </p>
              )}
            </div>

            {/* 새 포트폴리오 생성 */}
            <form onSubmit={handleCreatePortfolio} className="mt-3 flex gap-2">
              <input
                value={newName}
                onChange={e => setNewName(e.target.value)}
                placeholder="포트폴리오 이름"
                className="flex-1 px-3 py-1.5 rounded-lg bg-slate-700 border border-slate-600
                           text-white text-xs placeholder-slate-500
                           focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
              <button type="submit" disabled={creating || !newName.trim()}
                className="px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700
                           disabled:opacity-50 text-white text-xs transition-colors">
                +
              </button>
            </form>
          </div>
        </div>

        {/* 오른쪽: 선택 포트폴리오 상세 */}
        <div className="lg:col-span-3 space-y-6">

          {!selectedPortfolio ? (
            <div className="bg-slate-800 border border-dashed border-slate-600 rounded-xl
                            p-12 text-center text-slate-500">
              왼쪽에서 포트폴리오를 선택하거나 새로 만들어 보세요.
            </div>
          ) : (
            <>
              {/* 수익률 요약 카드 */}
              {loadingVal && (
                <div className="flex items-center gap-3 text-slate-400 text-sm">
                  <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
                  시장 데이터 조회 중…
                </div>
              )}

              {valuation && !loadingVal && (
                <PortfolioStats valuation={valuation} />
              )}

              {!valuation && !loadingVal && (
                <div className="bg-slate-800 border border-dashed border-slate-600
                                rounded-xl p-6 text-center text-slate-500 text-sm">
                  보유 종목을 등록하면 현재가 기준 수익률이 표시됩니다.
                </div>
              )}

              {/* 보유 종목 목록 */}
              {valuation?.holdings && valuation.holdings.length > 0 && (
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <h2 className="font-semibold text-white">보유 종목</h2>
                    <span className="text-xs text-slate-500">
                      환율: 1 USD = {valuation.usd_krw_rate.toLocaleString()}원 ({valuation.rate_source})
                    </span>
                  </div>
                  {valuation.holdings.map(h => (
                    <HoldingSummaryCard key={h.ticker} holding={h} />
                  ))}
                </div>
              )}

              {/* 종목 등록 토글 */}
              <div>
                <button
                  onClick={() => setShowAddHolding(v => !v)}
                  className="px-4 py-2 rounded-lg border border-blue-500/40 text-blue-400
                             hover:bg-blue-500/10 text-sm transition-colors"
                >
                  {showAddHolding ? '등록 취소' : '+ 종목 수동 등록'}
                </button>
              </div>

              {showAddHolding && (
                <AddHoldingForm
                  portfolioId={selectedPortfolio.id}
                  onAdded={() => {
                    setShowAddHolding(false)
                    // 수익률 재조회
                    if (selected) {
                      setLoadingVal(true)
                      getPortfolioValuation(selected)
                        .then(setValuation)
                        .catch(() => {})
                        .finally(() => setLoadingVal(false))
                    }
                  }}
                />
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
