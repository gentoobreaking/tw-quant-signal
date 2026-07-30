import { useQuery } from '@tanstack/react-query'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { api } from '../api/client'

interface QuarterlyFinancial {
  stock_id: string
  fiscal_quarter: string
  eps: number | null
  revenue: number | null
  gross_margin: number | null
  roe: number | null
  roa: number | null
}

function CustomTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  return (
    <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 6, padding: '8px 12px', fontSize: 12 }}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>{label}</div>
      {payload.map((p: any, i: number) => (
        <div key={i} style={{ color: p.color }}>{p.name}: {typeof p.value === 'number' ? p.value.toFixed(2) : '-'}</div>
      ))}
    </div>
  )
}

export default function QuarterlyFinancialsCard({ stockId }: { stockId: string }) {
  const { data, isLoading } = useQuery<QuarterlyFinancial[]>({
    queryKey: ['quarterly-financials', stockId],
    queryFn: () => api.quarterlyFinancials(stockId),
  })

  if (isLoading) return <div className="empty">載入中...</div>
  if (!data || data.length === 0) return null

  const chartData = [...data].reverse().slice(-12)

  return (
    <div className="card">
      <h2>📊 EPS（近 12 季）</h2>
      <div style={{ width: '100%', height: 260 }}>
        <ResponsiveContainer>
          <BarChart data={chartData} margin={{ top: 10, right: 20, bottom: 5, left: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis dataKey="fiscal_quarter" tick={{ fontSize: 11, fill: 'var(--text-dim)' }} interval={1} />
            <YAxis tick={{ fontSize: 11, fill: 'var(--text-dim)' }} tickFormatter={(v: number) => v.toFixed(1)} />
            <Tooltip content={<CustomTooltip />} />
            <Bar dataKey="eps" name="EPS" fill="var(--blue)" radius={[3, 3, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <table style={{ marginTop: 12 }}>
        <thead>
          <tr><th>季度</th><th>EPS</th><th>營收(百萬)</th><th>毛利率</th><th>ROE</th><th>ROA</th></tr>
        </thead>
        <tbody>
          {chartData.slice(-8).reverse().map(f => (
            <tr key={f.fiscal_quarter}>
              <td>{f.fiscal_quarter}</td>
              <td>{f.eps != null ? f.eps.toFixed(2) : '-'}</td>
              <td>{f.revenue != null ? (f.revenue / 1e8).toFixed(1) + '億' : '-'}</td>
              <td>{f.gross_margin != null ? `${f.gross_margin.toFixed(1)}%` : '-'}</td>
              <td className={(f.roe ?? 0) >= 15 ? 'text-green' : (f.roe ?? 0) < 5 ? 'text-red' : ''}>{f.roe != null ? `${f.roe.toFixed(1)}%` : '-'}</td>
              <td>{f.roa != null ? `${f.roa.toFixed(1)}%` : '-'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
