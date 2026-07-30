import { useQuery } from '@tanstack/react-query'
import { BarChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ComposedChart } from 'recharts'
import { api } from '../api/client'
import type { MonthlyRevenue } from '../api/client'

function CustomTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  return (
    <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 6, padding: '8px 12px', fontSize: 12 }}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>{label}</div>
      {payload.map((p: any, i: number) => (
        <div key={i} style={{ color: p.color }}>
          {p.name}: {typeof p.value === 'number' ? p.value.toLocaleString(undefined, { maximumFractionDigits: 1 }) : p.value}
          {p.name === '月營收' ? ' 千元' : '%'}
        </div>
      ))}
    </div>
  )
}

export default function MonthlyRevenueChart({ stockId }: { stockId: string }) {
  const { data, isLoading } = useQuery<MonthlyRevenue[]>({
    queryKey: ['monthly-revenue', stockId],
    queryFn: () => api.monthlyRevenue(stockId),
  })

  if (isLoading) return <div className="card"><h2>💰 月營收（近三年）</h2><div className="empty">載入中...</div></div>
  if (!data || data.length === 0) return <div className="card"><h2>💰 月營收（近三年）</h2><div className="empty">暫無資料</div></div>

  const chartData = [...data].reverse()

  return (
    <div className="card">
      <h2>💰 月營收（近三年）</h2>
      <div style={{ width: '100%', height: 320 }}>
        <ResponsiveContainer>
          <ComposedChart data={chartData} margin={{ top: 10, right: 20, bottom: 5, left: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis dataKey="year_month" tick={{ fontSize: 11, fill: 'var(--text-dim)' }} tickFormatter={(v: string) => v.slice(-4).replace('-', '/')} interval={2} />
            <YAxis yAxisId="left" tick={{ fontSize: 11, fill: 'var(--text-dim)' }} tickFormatter={(v: number) => `${(v / 1e6).toFixed(0)}M`} />
            <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11, fill: 'var(--text-dim)' }} domain={['dataMin - 5', 'dataMax + 5']} tickFormatter={(v: number) => `${v.toFixed(0)}%`} />
            <Tooltip content={<CustomTooltip />} />
            <Bar yAxisId="left" dataKey="revenue" name="月營收" fill="var(--blue)" opacity={0.6} radius={[3, 3, 0, 0]} />
            <Line yAxisId="right" type="monotone" dataKey="yoy_change" name="年增率" stroke="var(--green)" strokeWidth={2} dot={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <table style={{ marginTop: 12 }}>
        <thead>
          <tr><th>年月</th><th>營收(千元)</th><th>月增率</th><th>年增率</th></tr>
        </thead>
        <tbody>
          {chartData.slice(-12).reverse().map(r => (
            <tr key={r.year_month}>
              <td>{r.year_month}</td>
              <td>{r.revenue?.toLocaleString() ?? '-'}</td>
              <td className={(r.mom_change ?? 0) > 0 ? 'text-green' : (r.mom_change ?? 0) < 0 ? 'text-red' : ''}>{r.mom_change != null ? `${r.mom_change.toFixed(2)}%` : '-'}</td>
              <td className={(r.yoy_change ?? 0) > 0 ? 'text-green' : (r.yoy_change ?? 0) < 0 ? 'text-red' : ''}>{r.yoy_change != null ? `${r.yoy_change.toFixed(2)}%` : '-'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
