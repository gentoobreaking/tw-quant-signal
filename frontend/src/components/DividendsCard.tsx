import { useQuery } from '@tanstack/react-query'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { api } from '../api/client'
import type { Dividend } from '../api/client'

function CustomTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  return (
    <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 6, padding: '8px 12px', fontSize: 12 }}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>{label} 年</div>
      {payload.map((p: any, i: number) => (
        <div key={i} style={{ color: p.color }}>{p.name}: {typeof p.value === 'number' ? p.value.toFixed(2) : p.value}</div>
      ))}
    </div>
  )
}

export default function DividendsCard({ stockId }: { stockId: string }) {
  const { data, isLoading } = useQuery<Dividend[]>({
    queryKey: ['dividends', stockId],
    queryFn: () => api.dividends(stockId),
  })

  if (isLoading) return <div className="card"><h2>💵 股利分派（近 5 年）</h2><div className="empty">載入中...</div></div>
  if (!data || data.length === 0) return <div className="card"><h2>💵 股利分派（近 5 年）</h2><div className="empty">暫無資料</div></div>

  const sorted = [...data].sort((a, b) => a.year - b.year)

  return (
    <div className="card">
      <h2>💵 股利分派（近 5 年）</h2>
      <div style={{ width: '100%', height: 220 }}>
        <ResponsiveContainer>
          <BarChart data={sorted} margin={{ top: 10, right: 20, bottom: 5, left: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis dataKey="year" tick={{ fontSize: 11, fill: 'var(--text-dim)' }} />
            <YAxis tick={{ fontSize: 11, fill: 'var(--text-dim)' }} tickFormatter={(v: number) => `${v.toFixed(0)}`} />
            <Tooltip content={<CustomTooltip />} />
            <Bar dataKey="cash_dividend" name="現金股利" fill="var(--green)" radius={[3, 3, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <table style={{ marginTop: 12 }}>
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
          {sorted.reverse().map(d => (
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
