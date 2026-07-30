import type { HealthScore } from '../types'

const LIGHT_LABELS: Record<string, string> = {
  '🟢': '強勢多頭', '🟢🔴': '偏多', '🟡': '中立', '🔴🟢': '偏空', '🔴': '強勢空頭',
}
const LIGHT_CLASS: Record<string, string> = {
  '🟢': 'green', '🟢🔴': 'green-red', '🟡': 'yellow', '🔴🟢': 'red-green', '🔴': 'red',
}

interface Props {
  health: HealthScore | null | undefined
  weeklyHealth?: HealthScore | null | undefined
}

export default function HealthCheckCard({ health, weeklyHealth }: Props) {
  if (!health && !weeklyHealth) return null

  const showDaily = !!health
  const showWeekly = !!weeklyHealth

  return (
    <div className="card">
      <div className="flex-between mb-8" style={{ flexWrap: 'wrap', gap: 8 }}>
        <h2>🩺 四燈號健診</h2>
        {showDaily && (
          <span className={`light ${LIGHT_CLASS[health.total_light] || 'yellow'}`} style={{ fontSize: 12 }}>
            日 {health.total_light} {health.total_score.toFixed(0)}分 {LIGHT_LABELS[health.total_light] || ''}
          </span>
        )}
        {showWeekly && (
          <span className={`light ${LIGHT_CLASS[weeklyHealth.total_light] || 'yellow'}`} style={{ fontSize: 12 }}>
            週 {weeklyHealth.total_light} {weeklyHealth.total_score.toFixed(0)}分 {LIGHT_LABELS[weeklyHealth.total_light] || ''}
          </span>
        )}
      </div>

      {/* Daily */}
      {showDaily && (
        <div style={{ marginBottom: showWeekly ? 12 : 0 }}>
          <div className="text-dim" style={{ fontSize: 11, marginBottom: 6 }}>📅 日線級別</div>
          <div className="grid-4">
            {([
              ['基本面', health.fundamental_score, health.fundamental_light],
              ['籌碼面', health.institutional_score, health.institutional_light],
              ['技術面', health.technical_score, health.technical_light],
              ['估值面', health.valuation_score, health.valuation_light],
            ] as const).map(([label, score, light]) => (
              <div key={label} className="stat">
                <div className="label">{label}</div>
                <div className="value" style={{ fontSize: 16 }}>{score.toFixed(0)}</div>
                <div className={`light ${LIGHT_CLASS[light] || 'yellow'} mt-8`} style={{ fontSize: 11 }}>{light}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Weekly */}
      {showWeekly && (
        <div>
          <div className="text-dim" style={{ fontSize: 11, marginBottom: 6, borderTop: '1px solid var(--border)', paddingTop: 10 }}>
            📅 週線級別
          </div>
          <div className="grid-4">
            {([
              ['基本面', weeklyHealth.fundamental_score, weeklyHealth.fundamental_light],
              ['技術面', weeklyHealth.technical_score, weeklyHealth.technical_light],
              ['籌碼面', weeklyHealth.institutional_score, weeklyHealth.institutional_light],
              ['估值面', weeklyHealth.valuation_score, weeklyHealth.valuation_light],
            ] as const).map(([label, score, light]) => (
              <div key={'w-' + label} className="stat">
                <div className="label">{label}</div>
                <div className="value" style={{ fontSize: 16 }}>{score.toFixed(0)}</div>
                <div className={`light ${LIGHT_CLASS[light] || 'yellow'} mt-8`} style={{ fontSize: 11 }}>{light}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
