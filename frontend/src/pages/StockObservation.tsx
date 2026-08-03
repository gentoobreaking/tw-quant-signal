import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import HealthCheckCard from '../components/HealthCheckCard'
import RiskCard from '../components/RiskCard'
import PriceChart from '../components/PriceChart'
import SectorRankingCard from '../components/SectorRankingCard'
import HealthAspectDetail from '../components/HealthAspectDetail'
import MonthlyRevenueChart from '../components/MonthlyRevenueChart'
import QuarterlyFinancialsCard from '../components/QuarterlyFinancialsCard'
import DividendsCard from '../components/DividendsCard'
import InstitutionalFlowsCard from '../components/InstitutionalFlowsCard'
import MarginTradingCard from '../components/MarginTradingCard'
import type { StockDetail } from '../types'

const STATE_LABEL: Record<string, string> = {
  bull: '📈 多頭', bear: '📉 空頭', range: '➡️ 盤整',
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
        <HealthCheckCard health={data.health} weeklyHealth={data.weekly_health} monthlyHealth={data.monthly_health} />
        <RiskCard risk={data.risk} />
      </div>

      {/* Multi-timeframe consensus */}
      {data.multi_timeframe && (
        <div className="card">
          <div className="flex-between">
            <h2>🔗 多時間框架共識</h2>
            {(() => {
              const m = data.multi_timeframe
              const consensusColors: Record<string, string> = {
                strong_bullish: 'var(--green)',
                mild_bullish: 'var(--green)',
                neutral: 'var(--yellow)',
                mild_bearish: 'var(--red)',
                strong_bearish: 'var(--red)',
                conflicting: 'var(--yellow)',
              }
              const typeLabels: Record<string, string> = {
                short: '短線訊號 (1-5日)',
                swing: '波段訊號 (1-4週)',
                both: '短線+波段共振',
                neutral: '無明確方向',
              }
              return (
                <div style={{ textAlign: 'right', fontSize: 13 }}>
                  <div style={{ fontWeight: 700, color: consensusColors[m.consensus] || 'var(--text-dim)', fontSize: 15 }}>
                    {m.consensus_label}
                  </div>
                  <div className="text-dim" style={{ fontSize: 11 }}>{typeLabels[m.signal_type] || '中立'}</div>
                </div>
              )
            })()}
          </div>
          <div className="grid-2 mt-8">
            <div className="stat">
              <div className="label">日線燈號</div>
              <div className="value">{data.multi_timeframe.daily_light || '-'}</div>
              <div className="text-dim" style={{ fontSize: 11 }}>
                {data.multi_timeframe.details?.daily_score != null ? `${(data.multi_timeframe.details.daily_score as number).toFixed(0)}分` : '-'}
              </div>
            </div>
            <div className="stat">
              <div className="label">週線燈號</div>
              <div className="value">{data.multi_timeframe.weekly_light || '-'}</div>
              <div className="text-dim" style={{ fontSize: 11 }}>
                {data.multi_timeframe.details?.weekly_score != null ? `${(data.multi_timeframe.details.weekly_score as number).toFixed(0)}分` : '-'}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Chart */}
      <div className="card">
        <h2>📈 股價走勢</h2>
        <PriceChart prices={data.prices} indicators={data.indicators} />
      </div>

      {/* Health aspect details */}
      <HealthAspectDetail stockId={stockId} health={data.health} />

      {/* Signals */}
      {data.signals && (data.signals[0] as any)?.triggered_rules && (
        <div className="card">
          {(() => {
            let triggered: any[] = [];
            try { triggered = JSON.parse(data.signals[0].triggered_rules); } catch {}
            return <><h2>⚡ 觸發規則 ({triggered.length} 條)</h2>
            {triggered.length > 0 && <table>
              <thead><tr><th>規則</th><th>類型</th><th>名稱</th></tr></thead>
              <tbody>
                {triggered.map((tr: any, i: number) => (
                  <tr key={i}>
                    <td><code>{tr.rule_id}</code></td>
                    <td><span className={`light ${tr.type === 'bullish' ? 'green' : tr.type === 'bearish' ? 'red' : 'yellow'}`}>{tr.type}</span></td>
                    <td>{tr.rule_name}</td>
                  </tr>
                ))}
              </tbody>
            </table>}</>
          })()}
        </div>
      )}

      {/* Institutional flows (from detail API) */}
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

      {/* Monthly Revenue */}
      <MonthlyRevenueChart stockId={stockId} />

      {/* Quarterly Financials */}
      <QuarterlyFinancialsCard stockId={stockId} />
      <DividendsCard stockId={stockId} />
      <InstitutionalFlowsCard stockId={stockId} />
      <MarginTradingCard stockId={stockId} />
    </>
  )
}

export default function StockObservation({ selectedStockId }: { selectedStockId: string }) {
  return (
    <div>
      <SectorRankingCard stockId={selectedStockId} />
      <StockDetailView stockId={selectedStockId} />
    </div>
  )
}
