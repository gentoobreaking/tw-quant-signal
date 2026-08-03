import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Scorecard, ScorecardDetail } from '../types'

/**
 * T015 — 11 大指標多空訊號計分卡
 *
 * 雙欄佈局：多方表格（左，符合=紅）｜空方表格（右，符合=綠）
 * 不符合 = 灰色。每個指標行含類別（價量面/籌碼面/技術面/財務面）。
 */

interface IndicatorMeta {
  key: string
  label: string
  category: string
}

const BULLISH_META: IndicatorMeta[] = [
  { key: 'high_240d', label: '創 240 日新高', category: '價量面' },
  { key: 'inst_3d_buy', label: '三大法人連續 3 日買超', category: '籌碼面' },
  { key: 'foreign_buy_500', label: '外資買超 > 500 張', category: '籌碼面' },
  { key: 'foreign_3d_buy', label: '外資連買 3 日', category: '籌碼面' },
  { key: 'sity_buy_500', label: '投信買超 > 500 張', category: '籌碼面' },
  { key: 'sity_3d_buy', label: '投信連買 3 日', category: '籌碼面' },
  { key: 'proprietary_3d_buy', label: '主力連買 3 日', category: '籌碼面' },
  { key: 'red_3d', label: '連 3 日收紅 K 棒', category: '技術面' },
  { key: 'above_ma20', label: '站上月線', category: '技術面' },
  { key: 'revenue_yoy_up', label: '月營收成長 > 10%', category: '財務面' },
  { key: 'revenue_mom_up2', label: '月營收連續成長', category: '財務面' },
]

const BEARISH_META: IndicatorMeta[] = [
  { key: 'low_240d', label: '創 240 日新低', category: '價量面' },
  { key: 'inst_3d_sell', label: '三大法人連續 3 日賣超', category: '籌碼面' },
  { key: 'foreign_sell_500', label: '外資賣超 > 500 張', category: '籌碼面' },
  { key: 'foreign_3d_sell', label: '外資連賣 3 日', category: '籌碼面' },
  { key: 'sity_sell_500', label: '投信賣超 > 500 張', category: '籌碼面' },
  { key: 'sity_3d_sell', label: '投信連賣 3 日', category: '籌碼面' },
  { key: 'proprietary_3d_sell', label: '主力連賣 3 日', category: '籌碼面' },
  { key: 'black_3d', label: '連 3 日收黑 K 棒', category: '技術面' },
  { key: 'below_ma20', label: '跌破月線', category: '技術面' },
  { key: 'revenue_yoy_down', label: '月營收負成長 > 10%', category: '財務面' },
  { key: 'revenue_mom_down2', label: '月營收連續負成長', category: '財務面' },
]

const CATEGORY_ORDER = ['價量面', '籌碼面', '技術面', '財務面']

function IndicatorTable({ title, detail, meta, matchColor }: {
  title: string
  detail?: ScorecardDetail
  meta: IndicatorMeta[]
  matchColor: 'red' | 'green'
}) {
  const count = detail?.count ?? 0
  const total = meta.length
  const rows = CATEGORY_ORDER.flatMap(cat => {
    const items = meta.filter(m => m.category === cat)
    if (items.length === 0) return []
    return [
      <tr key={`cat-${cat}`} className="scorecard-category-row">
        <td colSpan={2} className="scorecard-category">{cat}</td>
      </tr>,
      ...items.map(m => {
        const matched = Boolean(detail?.[m.key])
        return (
          <tr key={m.key}>
            <td className={`scorecard-indicator ${matched ? `match-${matchColor}` : 'no-match'}`}>
              {matched ? '●' : '○'} {m.label}
            </td>
            <td className={`scorecard-check ${matched ? `match-${matchColor}` : 'no-match'}`}>
              {matched ? '✓' : '✗'}
            </td>
          </tr>
        )
      }),
    ]
  })

  return (
    <div className="card scorecard-panel">
      <h2 className="scorecard-title">{title}: {count}/{total}</h2>
      <table className="scorecard-table">
        <tbody>{rows}</tbody>
      </table>
    </div>
  )
}

export default function Scorecard({ stockId }: { stockId: string }) {
  const { data, isLoading, error } = useQuery<Scorecard>({
    queryKey: ['scorecard', stockId],
    queryFn: () => api.scorecard(stockId),
    refetchInterval: 60_000,
  })

  if (isLoading) return <div className="card empty">計分卡載入中...</div>
  if (error) return <div className="card empty text-red">計分卡讀取失敗</div>
  if (!data) return <div className="card empty">無計分卡資料</div>

  return (
    <div className="card">
      <div className="flex-between">
        <h2>📋 11 大指標多空計分卡</h2>
        <span className="text-dim" style={{ fontSize: 12 }}>
          {data.trade_date ? `更新日期: ${data.trade_date}` : ''}
        </span>
      </div>
      <div className="scorecard-grid">
        <IndicatorTable title="多方指標" detail={data.bullish} meta={BULLISH_META} matchColor="red" />
        <IndicatorTable title="空方指標" detail={data.bearish} meta={BEARISH_META} matchColor="green" />
      </div>
      <div className="text-dim" style={{ fontSize: 11, marginTop: 8 }}>
        說明：純標記式符合/不符合（不依賴權重）。多方符合顯示紅色、空方符合顯示綠色、不符合顯示灰色。紅色為多方、綠色為空方，並非漲跌顏色。
      </div>
    </div>
  )
}
