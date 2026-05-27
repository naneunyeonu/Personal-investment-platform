import type { PortfolioValuation } from '../../types/portfolio'

interface Props {
  valuation: PortfolioValuation
}

/** 수치를 한국식 통화 포맷으로 표시 */
const krwFmt = (v: number) =>
  new Intl.NumberFormat('ko-KR', { style: 'currency', currency: 'KRW', maximumFractionDigits: 0 }).format(v)

const pctFmt = (v: number) =>
  `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`

function StatCard({
  label,
  value,
  sub,
  positive,
}: {
  label: string
  value: string
  sub?: string
  positive?: boolean
}) {
  const colorClass =
    positive === undefined
      ? 'text-white'
      : positive
        ? 'text-green-400'
        : 'text-red-400'

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 flex flex-col gap-1">
      <p className="text-xs text-slate-400 font-medium uppercase tracking-wide">{label}</p>
      <p className={`text-2xl font-bold ${colorClass}`}>{value}</p>
      {sub && <p className="text-xs text-slate-500">{sub}</p>}
    </div>
  )
}

export default function PortfolioStats({ valuation }: Props) {
  const isPositive = valuation.total_return_pct >= 0

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
      <StatCard
        label="평가 금액"
        value={krwFmt(valuation.total_value_krw)}
      />
      <StatCard
        label="투자 원금"
        value={krwFmt(valuation.total_cost_krw)}
      />
      <StatCard
        label="총 수익률"
        value={pctFmt(valuation.total_return_pct)}
        positive={isPositive}
      />
      <StatCard
        label="평가 손익"
        value={krwFmt(valuation.total_value_krw - valuation.total_cost_krw)}
        sub={`주가 기여: ${krwFmt(valuation.price_contribution_krw)} / 환율 기여: ${krwFmt(valuation.fx_contribution_krw)}`}
        positive={isPositive}
      />
    </div>
  )
}
