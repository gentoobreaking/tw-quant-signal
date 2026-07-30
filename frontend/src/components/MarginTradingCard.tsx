import { useQuery } from '@tanstack/react-query'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts'
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

export default function MarginTradingCard({ stockId }: { stockId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['marginTrading', stockId],
    queryFn: () => api.marginTrading(stockId),
  })
  const rows: any[] = Array.isArray(data) ? data : []
  const chartData = [...rows].reverse()

  if (isLoading) return <div className="card"><h2>🔵 融資融券（近 20 日）</h2><div className="empty">載入中...</div></div>
  if (rows.length === 0) return <div className="card"><h2>🔵 融資融券（近 20 日）</h2><div className="empty">暫無資料</div></div>

  return (
    <div className="card">
      <h2>🔵 融資融券（近 20 日）</h2>
      <div style={{ width: '100%', height: 260 }}>
        <ResponsiveContainer>
          <LineChart data={chartData} margin={{ top: 10, right: 20, bottom: 5, left: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis dataKey="trade_date" tick={{ fontSize: 10, fill: 'var(--text-dim)' }} tickFormatter={(v: string) => v.slice(5)} interval={3} />
            <YAxis yAxisId="left" tick={{ fontSize: 11, fill: 'var(--text-dim)' }} tickFormatter={(v: number) => `${(v / 1000).toFixed(0)}K`} />
            <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11, fill: 'var(--text-dim)' }} tickFormatter={(v: number) => `${(v / 1000).toFixed(0)}K`} />
            <Tooltip content={<CustomTooltip />} />
            <Legend />
            <Line yAxisId="left" type="monotone" dataKey="margin_balance" name="融資餘額" stroke="var(--blue)" strokeWidth={2} dot={false} />
            <Line yAxisId="right" type="monotone" dataKey="short_balance" name="融券餘額" stroke="var(--red)" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <table style={{ marginTop: 12 }}>
        <thead>
          <tr><th>日期</th><th>融資買</th><th>融資賣</th><th>融資餘額</th><th>融券賣</th><th>融券買</th><th>融券餘額</th></tr>
        </thead>
        <tbody>
          {rows.slice(0, 20).map((r: any) => (
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
