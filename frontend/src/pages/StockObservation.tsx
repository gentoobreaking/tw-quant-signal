import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import HealthCheckCard from '../components/HealthCheckCard'
import RiskCard from '../components/RiskCard'
import PriceChart from '../components/PriceChart'
import type { StockDetail } from '../types'

const STATE_LABEL: Record<string, string> = {
  bull: '📈 多頭', bear: '📉 空頭', range: '➡️ 盤整',
}
const STOCK_NAMES: Record<string, string> = {
  '2330': '台積電', '0050': '元大台灣50', '2308': '台達電',
}

function StockDetailView({ stockId }: { stockId: string }) {
  const { data, isLoading, error } = useQuery<StockDetail>({
    queryKey: ['stock-detail', stockId],
    queryFn: () => api.stockDetail(stockId),
    refetchInterval: 60_000,
  })

  if (isLoading) return <div className="empty">載入中...</div>
  if (error) return <div className="empty text-red">讀取失敗</div>
  if (!data) return <div className="empty">無資料</div>

  const latest = data.prices?.[0]
  const ind = data.indicators?.[0]

  return (
    <>
      {/* Stock header */}
      <div className="card flex-between">
        <div>
          <h2 style={{ fontSize: 18 }}>{stockId} {data.name}</h2>
          {data.market_state && (
            <span className="text-dim" style={{ fontSize: 12 }}>
              {STATE_LABEL[data.market_state.state] || data.market_state.state}
              {' '}收盤 {data.market_state.close.toFixed(0)} MA60 {data.market_state.ma60.toFixed(0)} RSI {data.market_state.rsi.toFixed(1)}
            </span>
          )}
        </div>
        <div>
          <div style={{ fontSize: 26, fontWeight: 700, textAlign: 'right' }}>{latest?.close?.toFixed(2) || '-'}</div>
          {latest?.change_pct != null && (
            <div style={{ fontSize: 14, textAlign: 'right' }} className={latest.change_pct >= 0 ? 'text-green' : 'text-red'}>
              {latest.change_pct >= 0 ? '+' : ''}{latest.change_pct.toFixed(2)}%
            </div>
          )}
        </div>
      </div>

      {/* Health + Risk */}
      <div className="grid-2">
        <HealthCheckCard health={data.health} />
        <RiskCard risk={data.risk} />
      </div>

      {/* Chart */}
      <div className="card">
        <h2>📈 股價走勢</h2>
        <PriceChart prices={data.prices} indicators={data.indicators} />
      </div>

      {/* Signals */}
      {data.signals && (data.signals[0] as any)?.triggered_rules && (
        <div className="card">
          <h2>⚡ 觸發規則 ({data.signals[0].triggered_rules.length} 條)</h2>
          <table>
            <thead><tr><th>規則</th><th>類型</th><th>名稱</th></tr></thead>
            <tbody>
              {(JSON.parse(data.signals[0].triggered_rules) as any[]).map((tr: any, i: number) => (
                <tr key={i}>
                  <td><code>{tr.rule_id}</code></td>
                  <td><span className={`light ${tr.type === 'bullish' ? 'green' : tr.type === 'bearish' ? 'red' : 'yellow'}`}>{tr.type}</span></td>
                  <td>{tr.rule_name}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Institutional flows */}
      {data.institutional && data.institutional.length > 0 && (
        <div className="card">
          <h2>🏦 法人買賣超 (近10日)</h2>
          <table>
            <thead><tr><th>日期</th><th>外資</th><th>投信</th><th>自營商</th></tr></thead>
            <tbody>
              {data.institutional.slice(0, 10).map(inst => (
                <tr key={inst.date}>
                  <td>{inst.date}</td>
                  <td className={inst.foreign != null && inst.foreign > 0 ? 'text-green' : 'text-red'}>{inst.foreign != null ? (inst.foreign / 1000).toFixed(0) : '-'}k</td>
                  <td className={inst.sity != null && inst.sity > 0 ? 'text-green' : 'text-red'}>{inst.sity != null ? (inst.sity / 1000).toFixed(0) : '-'}k</td>
                  <td className={inst.dealer != null && inst.dealer > 0 ? 'text-green' : 'text-red'}>{inst.dealer != null ? (inst.dealer / 1000).toFixed(0) : '-'}k</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Financials */}
      {data.financials && data.financials.length > 0 && (
        <div className="card">
          <h2>📋 財務數據</h2>
          <table>
            <thead><tr><th>季度</th><th>EPS</th><th>營收</th><th>毛利率</th></tr></thead>
            <tbody>
              {data.financials.slice(0, 8).map(f => (
                <tr key={f.quarter}>
                  <td>{f.quarter}</td>
                  <td>{f.eps ?? '-'}</td>
                  <td>{f.revenue != null ? `${(f.revenue / 1e8).toFixed(1)}億` : '-'}</td>
                  <td>{f.gross_margin != null ? `${(f.gross_margin * 100).toFixed(1)}%` : '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}

export default function StockObservation() {
  const { data: stocks } = useQuery({
    queryKey: ['stocks'],
    queryFn: () => api.listStocks(),
    refetchInterval: 60_000,
  })

  const [selected, setSelected] = useState<string>('2330')

  return (
    <div>
      <div className="stock-tabs">
        {(stocks || []).map(s => (
          <div
            key={s.id}
            className={`stock-tab ${selected === s.id ? 'active' : ''}`}
            onClick={() => setSelected(s.id)}
          >
            {s.id} {s.name}
          </div>
        ))}
      </div>
      {selected && <StockDetailView stockId={selected} />}
    </div>
  )
}
