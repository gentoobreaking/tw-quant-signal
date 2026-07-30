import { useQuery } from '@tanstack/react-query'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { api } from '../api/client'

function CustomTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  return (
    <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 6, padding: '8px 12px', fontSize: 12 }}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>{label}</div>
      {payload.map((p: any, i: number) => (
        <div key={i} style={{ color: p.color }}>{p.name}: {typeof p.value === 'number' ? p.value.toLocaleString() : p.value}</div>
      ))}
    </div>
  )
}

export default function InstitutionalFlowsCard({ stockId }: { stockId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['institutionalFlows', stockId],
    queryFn: () => api.institutionalFlows(stockId),
  })
  const rows: any[] = Array.isArray(data) ? data : []
  const chartData = [...rows].reverse().slice(-20)

  if (isLoading) return <div className="card"><h2>🏢 法人買賣超（近 20 日）</h2><div className="empty">載入中...</div></div>
  if (rows.length === 0) return <div className="card"><h2>🏢 法人買賣超（近 20 日）</h2><div className="empty">暫無資料</div></div>

  const tableRows = rows.slice(0, 20)

  return (
    <div className="card">
      <h2>🏢 法人買賣超（近 20 日）</h2>
      <div style={{ width: '100%', height: 260 }}>
        <ResponsiveContainer>
          <BarChart data={chartData} margin={{ top: 10, right: 20, bottom: 5, left: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis dataKey="trade_date" tick={{ fontSize: 10, fill: 'var(--text-dim)' }} tickFormatter={(v: string) => v.slice(5)} interval={3} />
            <YAxis tick={{ fontSize: 11, fill: 'var(--text-dim)' }} tickFormatter={(v: number) => `${(v / 1000).toFixed(0)}K`} />
            <Tooltip content={<CustomTooltip />} />
            <Bar dataKey="foreign_investors_net" name="外資" fill="var(--blue)" radius={[2, 2, 0, 0]} />
            <Bar dataKey="sity_investors_net" name="投信" fill="var(--green)" radius={[2, 2, 0, 0]} />
            <Bar dataKey="dealer_net" name="自營商" fill="var(--yellow)" radius={[2, 2, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <table style={{ marginTop: 12 }}>
        <thead>
          <tr><th>日期</th><th>外資</th><th>投信</th><th>自營商</th><th>自營(避險)</th><th>合計</th></tr>
        </thead>
        <tbody>
          {tableRows.map((r: any) => (
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
