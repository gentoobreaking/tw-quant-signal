import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'

export default function MarginTradingCard({ stockId }: { stockId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['marginTrading', stockId],
    queryFn: () => api.marginTrading(stockId),
  })
  const rows = Array.isArray(data) ? data.slice(0, 20) : []

  if (isLoading) return <div className="empty">載入中...</div>
  if (rows.length === 0) return null

  return (
    <div className="card">
      <h2>🔵 融資融券（近 20 日）</h2>
      <table>
        <thead>
          <tr>
            <th>日期</th>
            <th>融資買</th>
            <th>融資賣</th>
            <th>融資餘額</th>
            <th>融券賣</th>
            <th>融券買</th>
            <th>融券餘額</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r: any) => (
            <tr key={r.trade_date}>
              <td>{r.trade_date}</td>
              <td>{(r.margin_buy ?? 0).toLocaleString()}</td>
              <td>{(r.margin_sell ?? 0).toLocaleString()}</td>
              <td style={{ fontWeight: 600 }}>{(r.margin_balance ?? 0).toLocaleString()}</td>
              <td>{(r.short_sell ?? 0).toLocaleString()}</td>
              <td>{(r.short_buy ?? 0).toLocaleString()}</td>
              <td style={{ fontWeight: 600 }}>{(r.short_balance ?? 0).toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
