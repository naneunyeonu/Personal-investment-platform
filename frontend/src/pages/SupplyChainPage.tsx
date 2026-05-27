/**
 * SupplyChainPage — 밸류체인(공급망) 시각화 지도
 *
 * architecture_plan.md §7 구현:
 *   - Leaflet 기반 세계 지도 위에 공급망 노드(Point) / 에지(LineString) 렌더링
 *   - 지정학적 리스크 분석 패널 (Gemini AI → Celery 비동기)
 */

import { useState } from 'react'
import SupplyChainMap from '../components/supply-chain/SupplyChainMap'
import { analyzeGeopoliticalRisk } from '../api/supplyChain'

export default function SupplyChainPage() {
  // ── 필터 ────────────────────────────────────────────────────────────────
  const [tickerInput, setTickerInput] = useState('')
  const [tickers, setTickers]         = useState<string[] | undefined>(undefined)
  const [includeEdges, setIncludeEdges] = useState(true)

  const applyFilter = () => {
    const list = tickerInput
      .split(/[,\s]+/)
      .map(t => t.trim().toUpperCase())
      .filter(Boolean)
    setTickers(list.length > 0 ? list : undefined)
  }

  // ── 리스크 분석 패널 ────────────────────────────────────────────────────
  const [newsText,  setNewsText]  = useState('')
  const [analyzing, setAnalyzing] = useState(false)
  const [taskId,    setTaskId]    = useState<string | null>(null)
  const [riskError, setRiskError] = useState<string | null>(null)

  const handleAnalyze = async () => {
    if (!newsText.trim()) return
    setAnalyzing(true)
    setRiskError(null)
    setTaskId(null)
    try {
      const res = await analyzeGeopoliticalRisk({
        news_text: newsText,
        portfolio_tickers: tickers ?? [],
      })
      setTaskId(res.task_id)
    } catch {
      setRiskError('분석 요청에 실패했습니다. 백엔드 연결을 확인해 주세요.')
    } finally {
      setAnalyzing(false)
    }
  }

  return (
    <div className="space-y-6">

      {/* 헤더 */}
      <div>
        <h1 className="text-2xl font-bold text-white">공급망 시각화 지도</h1>
        <p className="text-slate-400 text-sm mt-1">
          밸류체인 노드를 지도 위에서 탐색하고, 지정학적 리스크 파급 효과를 분석합니다.
        </p>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-4 gap-6">

        {/* 왼쪽: 지도 */}
        <div className="xl:col-span-3 space-y-4">

          {/* 필터 컨트롤 */}
          <div className="bg-slate-800 border border-slate-700 rounded-xl p-4
                          flex flex-wrap items-center gap-3">
            <input
              value={tickerInput}
              onChange={e => setTickerInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && applyFilter()}
              placeholder="티커 필터 (예: AAPL, TSLA)"
              className="flex-1 min-w-0 px-3 py-2 rounded-lg bg-slate-700 border border-slate-600
                         text-white text-sm placeholder-slate-500
                         focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <button onClick={applyFilter}
              className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm
                         transition-colors shrink-0">
              필터 적용
            </button>
            <label className="flex items-center gap-2 text-sm text-slate-300 shrink-0">
              <input
                type="checkbox"
                checked={includeEdges}
                onChange={e => setIncludeEdges(e.target.checked)}
                className="w-4 h-4 accent-blue-500"
              />
              에지 표시
            </label>
            {tickers && (
              <button
                onClick={() => { setTickers(undefined); setTickerInput('') }}
                className="text-xs text-slate-400 hover:text-white transition-colors shrink-0"
              >
                필터 초기화
              </button>
            )}
          </div>

          {/* 지도 */}
          <div className="h-[540px]">
            <SupplyChainMap tickers={tickers} includeEdges={includeEdges} />
          </div>
        </div>

        {/* 오른쪽: 지정학적 리스크 분석 패널 */}
        <div className="xl:col-span-1 space-y-4">

          <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 space-y-4">
            <div>
              <h2 className="font-semibold text-white text-sm">🌐 지정학적 리스크 분석</h2>
              <p className="text-xs text-slate-500 mt-1">
                뉴스 텍스트를 입력하면 Gemini AI가 공급망 파급 효과를 분석합니다.
              </p>
            </div>

            <textarea
              value={newsText}
              onChange={e => setNewsText(e.target.value)}
              rows={6}
              placeholder="분석할 지정학적 이벤트 뉴스를 입력하세요.&#10;(예: 대만 해협 긴장 고조, 반도체 수출 규제 등)"
              className="w-full px-3 py-2.5 rounded-lg bg-slate-700 border border-slate-600
                         text-white text-sm placeholder-slate-500 resize-none
                         focus:outline-none focus:ring-2 focus:ring-blue-500"
            />

            <button
              onClick={handleAnalyze}
              disabled={analyzing || !newsText.trim()}
              className="w-full py-2.5 rounded-lg bg-blue-600 hover:bg-blue-700
                         disabled:opacity-50 text-white text-sm font-semibold
                         transition-colors"
            >
              {analyzing ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="w-4 h-4 border-2 border-white border-t-transparent
                                   rounded-full animate-spin" />
                  분석 요청 중…
                </span>
              ) : 'AI 리스크 분석 요청'}
            </button>

            {riskError && (
              <p className="text-red-400 text-xs bg-red-500/10 border border-red-500/30
                            rounded-lg px-3 py-2">
                {riskError}
              </p>
            )}

            {taskId && (
              <div className="bg-green-500/10 border border-green-500/30 rounded-lg p-3 space-y-1">
                <p className="text-green-400 text-xs font-semibold">✅ 분석 작업이 시작되었습니다</p>
                <p className="text-slate-400 text-xs break-all">
                  Task ID: <code className="text-slate-300">{taskId}</code>
                </p>
                <p className="text-slate-500 text-xs">
                  Celery 백그라운드에서 처리 중입니다. 결과는 Redis에 저장됩니다.
                </p>
              </div>
            )}
          </div>

          {/* 리스크 레벨 가이드 */}
          <div className="bg-slate-800 border border-slate-700 rounded-xl p-4 space-y-3">
            <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wide">
              노드 유형 안내
            </h3>
            {[
              { icon: '🏢', label: 'COMPANY', desc: '상장 기업' },
              { icon: '🏭', label: 'FACTORY', desc: '생산 공장' },
              { icon: '⚓', label: 'PORT', desc: '항구 / 물류 게이트웨이' },
              { icon: '📦', label: 'LOGISTICS_HUB', desc: '물류 허브' },
              { icon: '⛏', label: 'RAW_MATERIAL', desc: '원자재 생산지' },
            ].map(({ icon, label, desc }) => (
              <div key={label} className="flex items-center gap-2 text-xs text-slate-300">
                <span>{icon}</span>
                <span className="font-mono text-slate-400">{label}</span>
                <span className="text-slate-500">— {desc}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
