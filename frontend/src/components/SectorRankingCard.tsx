import { useQuery } from '@tanstack/react-query'
import { api, type StockSectorRank } from '../api/client'

interface SectorRank {
  sector: string
  count: number
  avg_score: number
  members: { stock_id: string; stock_name: string; score: number }[]
}

function Pct({ v }: { v: number | null }) {
  if (v == null) return <span className="text-dim">-</span>
  const cls = v <= 25 ? 'text-green' : v <= 50 ? '' : 'text-red'
  return <span className={cls}>{v.toFixed(0)}%</span>
}

export default function SectorRankingCard({ stockId }: { stockId?: string }) {
  const { data, isLoading } = useQuery<SectorRank[]>({
    queryKey: ['sectorRanking'],
    queryFn: () => api.sectorRanking(),
  })

  const { data: stockRank, isLoading: rankLoading } = useQuery<StockSectorRank>({
    queryKey: ['stockSectorRanking', stockId],
    queryFn: () => api.stockSectorRanking(stockId!),
    enabled: !!stockId,
  })

  return (
    <div className="card">
      <h2>🏭 類股排行</h2>
      {stockId && stockRank && (
        <div style={{ marginBottom: 14, padding: '10px 12px', background: 'var(--bg-sub, rgba(0,0,0,0.03))', borderRadius: 8 }}>
          <div style={{ fontWeight: 600, marginBottom: 6 }}>
            {stockRank.stock_name ?? stockRank.stock_id}
            {stockRank.sector ? ` · ${stockRank.sector}` : ' · 未分類'} 
            <small style={{ marginLeft: 8 }}>類股 {stockRank.member_count} 檔</small>
          </div>
          {stockRank.sector ? (
            <div style={{ display: 'flex', gap: 18, fontSize: 13, flexWrap: 'wrap' }}>
              <span>EPS 百分位 <Pct v={stockRank.percentiles.eps} /></span>
              <span>ROE 百分位 <Pct v={stockRank.percentiles.roe} /></span>
              <span>ROA 百分位 <Pct v={stockRank.percentiles.roa} /></span>
              <span style={{ color: 'var(--text-dim)' }}>（越小越靠前）</span>
            </div>
          ) : (
            <div style={{ fontSize: 13, color: 'var(--text-dim)' }}>尚無類股歸屬或季度資料</div>
          )}
          {stockRank.sector && stockRank.members.length > 1 && (
            <table style={{ marginTop: 8, fontSize: 12 }}>
              <thead>
                <tr><th>個股</th><th>EPS</th><th>ROE</th><th>ROA</th><th>季度</th></tr>
              </thead>
              <tbody>
                {stockRank.members.map(m => (
                  <tr key={m.stock_id} style={{ fontWeight: m.stock_id === stockId ? 700 : 400 }}>
                    <td>{m.stock_name ?? m.stock_id}</td>
                    <td>{m.eps != null ? m.eps.toFixed(2) : '-'}</td>
                    <td>{m.roe != null ? `${m.roe.toFixed(1)}%` : '-'}</td>
                    <td>{m.roa != null ? `${m.roa.toFixed(1)}%` : '-'}</td>
                    <td>{m.fiscal_quarter ?? '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
      {isLoading ? (
        <div className="empty">載入中...</div>
      ) : !data || data.length === 0 ? (
        <div className="empty">暫無資料</div>
      ) : (
        <table>
          <thead>
            <tr><th>類股</th><th>檔數</th><th>平均分數</th><th>個股</th></tr>
          </thead>
          <tbody>
            {data.map(sr => (
              <tr key={sr.sector}>
                <td style={{ fontWeight: 600 }}>{sr.sector}</td>
                <td>{sr.count}</td>
                <td className={sr.avg_score >= 60 ? 'text-green' : sr.avg_score >= 40 ? '' : 'text-red'}>{sr.avg_score}</td>
                <td style={{ fontSize: '13px' }}>
                  {sr.members.map(m => (
                    <span key={m.stock_id} style={{ marginRight: 12, whiteSpace: 'nowrap' }}>
                      {m.stock_name ?? m.stock_id} <small>({m.score})</small>
                    </span>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
