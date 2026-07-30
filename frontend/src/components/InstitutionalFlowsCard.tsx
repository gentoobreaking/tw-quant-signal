import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'

export default function InstitutionalFlowsCard({ stockId }: { stockId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['institutionalFlows', stockId],
    queryFn: () => api.institutionalFlows(stockId),
  })
  const rows = Array.isArray(data) ? data.slice(0, 20) : []

  if (isLoading) return <div className="empty">載入中...</div>
  if (rows.length === 0) return null

  return (
    <div className="card">
      <h2>🏢 法人買賣超（近 20 日）</h2>
      <table>
        <thead>
          <tr>
            <th>日期</th>
            <th>外資</th>
            <th>投信</th>
            <th>自營商</th>
            <th>自營(避險)</th>
            <th>合計</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r: any) => (
            <tr key={r.trade_date}>
              <td>{r.trade_date}</td>
              <td className={r.foreign_investors_net > 0 ? 'text-green' : r.foreign_investors_net < 0 ? 'text-red' : ''}>{r.foreign_investors_net?.toLocaleString()}</td>
              <td className={r.sity_investors_net > 0 ? 'text-green' : r.sity_investors_net < 0 ? 'text-red' : ''}>{r.sity_investors_net?.toLocaleString()}</td>
              <td className={r.dealer_net > 0 ? 'text-green' : r.dealer_net < 0 ? 'text-red' : ''}>{r.dealer_net?.toLocaleString()}</td>
              <td>{r.dealer_hedge_net?.toLocaleString()}</td>
              <td className={r.total_net > 0 ? 'text-green' : r.total_net < 0 ? 'text-red' : ''} style={{ fontWeight: 600 }}>{r.total_net?.toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
