import { useQuery } from '@tanstack/react-query'
import { RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Radar, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts'
import { api } from '../api/client'
import type { Stock, HealthScore } from '../types'

const ASPECT_LABELS: Record<string, string> = {
  fundamental_score: '基本面',
  institutional_score: '籌碼面',
  technical_score: '技術面',
  valuation_score: '估值面',
}

const ASPECT_COLORS: Record<string, string> = {
  fundamental_score: '#42a5f5',
  institutional_score: '#26a69a',
  technical_score: '#ffa726',
  valuation_score: '#ab47bc',
}

export default function DashboardCharts() {
  const { data: stocks } = useQuery({
    queryKey: ['stocks'],
    queryFn: () => api.listStocks(),
    refetchInterval: 60_000,
  })
  const { data: healthScores } = useQuery({
    queryKey: ['health'],
    queryFn: () => api.healthScores(),
    refetchInterval: 60_000,
  })
  const { data: marketState } = useQuery({
    queryKey: ['market-state'],
    queryFn: () => api.marketState(),
    refetchInterval: 60_000,
  })

  if (!stocks || stocks.length === 0) return null

  // Health score bar chart data
  const barData = stocks.map(s => ({
    name: s.id,
    score: s.health_score ?? 0,
    risk: s.risk_score ?? 0,
  }))

  // Radar data: each stock becomes a series
  const radarData = (healthScores || []).map(h => ({
    aspect: ASPECT_LABELS[h.stock_id + '_score'] || h.stock_id,
    基本面: h.fundamental_score,
    籌碼面: h.institutional_score,
    技術面: h.technical_score,
    估值面: h.valuation_score,
  }))

  // Per-stock radar data (aspects as rows)
  const aspectKeys = ['fundamental_score', 'institutional_score', 'technical_score', 'valuation_score']
  const stockRadarData = aspectKeys.map(key => {
    const row: Record<string, any> = { aspect: ASPECT_LABELS[key] }
    for (const h of (healthScores || [])) {
      row[h.stock_id] = (h as any)[key] ?? 0
    }
    return row
  })

  const stockIds = (healthScores || []).map(h => h.stock_id)
  const colors = ['#42a5f5', '#26a69a', '#ffa726', '#ef5350', '#ab47bc', '#66bb6a']

  return (
    <div className="card">
      <h2>📊 儀表板總覽</h2>
      <div className="grid-2" style={{ marginTop: 8 }}>
        {/* Market state */}
        {marketState && (
          <div className="stat" style={{ textAlign: 'left', minWidth: 'auto', padding: 0 }}>
            <div className="label">大盤狀態</div>
            <div style={{ fontSize: 18, fontWeight: 600 }}>
              {marketState.state === 'bull' ? '📈 多頭' : marketState.state === 'bear' ? '📉 空頭' : '➡️ 盤整'}
            </div>
            <div className="text-dim" style={{ fontSize: 12, marginTop: 4 }}>
              收盤 {marketState.close.toFixed(0)} / MA60 {marketState.ma60.toFixed(0)} / RSI {marketState.rsi.toFixed(1)}
            </div>
          </div>
        )}

        {/* Summary stats */}
        {stocks.length > 0 && (
          <div style={{ display: 'flex', gap: 16, justifyContent: 'flex-end' }}>
            {(() => {
              const avgHealth = stocks.reduce((s, st) => s + (st.health_score ?? 0), 0) / stocks.length
              const maxRisk = Math.max(...stocks.map(s => s.risk_score ?? 0))
              return <>
                <div className="stat" style={{ minWidth: 80, padding: 0 }}>
                  <div className="label">平均健診</div>
                  <div className="value" style={{ fontSize: 20 }}>{avgHealth.toFixed(0)}</div>
                </div>
                <div className="stat" style={{ minWidth: 80, padding: 0 }}>
                  <div className="label">最高風險</div>
                  <div className="value" style={{ fontSize: 20, color: maxRisk >= 60 ? 'var(--orange)' : 'var(--text)' }}>{maxRisk}</div>
                </div>
              </>
            })()}
          </div>
        )}
      </div>

      {/* Health score bar chart */}
      <h3 className="mt-16">健診 vs 風險分數</h3>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={barData} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#2a2d3a" />
          <XAxis dataKey="name" stroke="#888ca6" fontSize={12} />
          <YAxis stroke="#888ca6" fontSize={12} />
          <Tooltip
            contentStyle={{ background: '#1a1d28', border: '1px solid #2a2d3a', borderRadius: 6, fontSize: 12 }}
            labelStyle={{ color: '#e4e6f0' }}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Bar dataKey="score" name="健診分數" fill="#26a69a" radius={[4, 4, 0, 0]} />
          <Bar dataKey="risk" name="風險分數" fill="#ef5350" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>

      {/* Radar chart - 4 aspects by stock */}
      <h3 className="mt-16">四面向強弱雷達圖</h3>
      <ResponsiveContainer width="100%" height={260}>
        <RadarChart data={stockRadarData} margin={{ top: 5, right: 30, bottom: 5, left: 30 }}>
          <PolarGrid stroke="#2a2d3a" />
          <PolarAngleAxis dataKey="aspect" stroke="#888ca6" fontSize={12} />
          <PolarRadiusAxis angle={90} domain={[0, 100]} stroke="#2a2d3a" fontSize={10} />
          {stockIds.map((sid, i) => (
            <Radar key={sid} name={sid} dataKey={sid} stroke={colors[i % colors.length]} fill={colors[i % colors.length]} fillOpacity={0.1} />
          ))}
          <Legend wrapperStyle={{ fontSize: 12 }} />
        </RadarChart>
      </ResponsiveContainer>
    </div>
  )
}
