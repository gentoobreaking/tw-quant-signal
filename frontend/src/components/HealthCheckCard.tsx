import { useQuery } from '@tanstack/react-query'
import type { HealthScore } from '../types'

const LIGHT_LABELS: Record<string, string> = {
  '🟢': '強勢多頭', '🟢🔴': '偏多', '🟡': '中立', '🔴🟢': '偏空', '🔴': '強勢空頭',
}
const LIGHT_CLASS: Record<string, string> = {
  '🟢': 'green', '🟢🔴': 'green-red', '🟡': 'yellow', '🔴🟢': 'red-green', '🔴': 'red',
}

export default function HealthCheckCard({ health }: { health: HealthScore | null | undefined }) {
  if (!health) return null
  const cls = LIGHT_CLASS[health.total_light] || 'yellow'
  return (
    <div className="card">
      <div className="flex-between mb-8">
        <h2>🩺 四燈號健診</h2>
        <span className={`light ${cls}`}>{health.total_light} {health.total_score.toFixed(0)} 分 {LIGHT_LABELS[health.total_light] || ''}</span>
      </div>
      <div className="grid-4">
        {([
          ['基本面', health.fundamental_score, health.fundamental_light],
          ['籌碼面', health.institutional_score, health.institutional_light],
          ['技術面', health.technical_score, health.technical_light],
          ['估值面', health.valuation_score, health.valuation_light],
        ] as const).map(([label, score, light]) => (
          <div key={label} className="stat">
            <div className="label">{label}</div>
            <div className="value" style={{ fontSize: 18 }}>{score.toFixed(0)}</div>
            <div className={`light ${LIGHT_CLASS[light] || 'yellow'} mt-8`} style={{ fontSize: 11 }}>{light}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
