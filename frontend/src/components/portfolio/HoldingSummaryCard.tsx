import type { HoldingValuation } from '../../types/portfolio'

interface Props {
  holding: HoldingValuation
}

const krwFmt = (v: number) =>
  new Intl.NumberFormat('ko-KR', {
    style: 'currency', currency: 'KRW', maximumFractionDigits: 0,
  }).format(v)

const pctFmt = (v: number) => `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`

export default function HoldingSummaryCard({ holding }: Props) {
  const isPositive = holding.gain_loss_pct >= 0
  const gainColor  = isPositive ? 'text-green-400' : 'text-red-400'
  const badgeBg    = isPositive ? 'bg-green-500/15 border-green-500/30' : 'bg-red-500/15 border-red-500/30'

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl p-4 flex items-center justify-between gap-4">

      {/* 종목 정보 */}
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-bold text-white text-base">{holding.ticker}</span>
          <span className="text-xs text-slate-400">{holding.currency_code}</span>
        </div>
        <div className="text-xs text-slate-400 mt-0.5">
          {holding.quantity.toLocaleString()}주 · 평단가{' '}
          {holding.average_cost.toLocaleString(undefined, { maximumFractionDigits: 2 })}
        </div>
      </div>

      {/* 현재가 */}
      <div className="text-right hidden sm:block">
        <div className="text-sm text-slate-300 font-medium">
          {holding.current_price.toLocaleString(undefined, { maximumFractionDigits: 2 })}
        </div>
        <div className="text-xs text-slate-500">현재가</div>
      </div>

      {/* 수익률 배지 */}
      <div className={`px-3 py-1.5 rounded-lg border text-right shrink-0 ${badgeBg}`}>
        <div className={`font-bold ${gainColor}`}>
          {pctFmt(holding.gain_loss_pct)}
        </div>
        <div className={`text-xs ${gainColor}`}>
          {krwFmt(holding.gain_loss_krw)}
        </div>
      </div>

      {/* 평가금액 */}
      <div className="text-right hidden md:block">
        <div className="text-sm font-semibold text-white">
          {krwFmt(holding.current_price_krw)}
        </div>
        <div className="text-xs text-slate-500">평가금액</div>
      </div>
    </div>
  )
}
