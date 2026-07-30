import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Dividend } from '../api/client'

export default function DividendsCard({ stockId }: { stockId: string }) {
  const { data, isLoading } = useQuery<Dividend[]>({
    queryKey: ['dividends', stockId],
    queryFn: () => api.dividends(stockId),
  })

  if (isLoading) return <div className="empty">載入中...</div>
  if (!data || data.length === 0) return null

  return (
    <div className="card">
      <h2>💵 股利分派（近 5 年）</h2>
      <table>
        <thead>
          <tr>
            <th>年度</th>
            <th>除權息日</th>
            <th>除權前收盤</th>
            <th>現金股利</th>
            <th>現金殖利率</th>
            <th>股票股利</th>
          </tr>
        </thead>
        <tbody>
          {data.map(d => (
            <tr key={d.year}>
              <td>{d.year}</td>
              <td>{d.ex_date || '-'}</td>
              <td>{d.close_before_ex != null ? d.close_before_ex.toFixed(2) : '-'}</td>
              <td style={{ fontWeight: 600 }}>{d.cash_dividend != null ? `${d.cash_dividend.toFixed(2)} 元` : '-'}</td>
              <td className="text-green">{d.cash_yield != null ? `${d.cash_yield.toFixed(2)}%` : '-'}</td>
              <td>{d.stock_dividend != null ? `${d.stock_dividend.toFixed(2)} 元` : '-'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
