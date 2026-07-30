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
  monthlyHealth?: HealthScore | null | undefined
}

export default function HealthCheckCard({ health, weeklyHealth, monthlyHealth }: Props) {
  if (!health && !weeklyHealth && !monthlyHealth) return null

  const showDaily = !!health
  const showWeekly = !!weeklyHealth
  const showMonthly = !!monthlyHealth

  const aspects: [string, string, string][] = [
    ['基本面', 'fundamental_score', 'fundamental_light'],
    ['籌碼面', 'institutional_score', 'institutional_light'],
    ['技術面', 'technical_score', 'technical_light'],
    ['估值面', 'valuation_score', 'valuation_light'],
  ]

  return (
    <div className="card">
      <div className="flex-between mb-8" style={{ flexWrap: 'wrap', gap: 8 }}>
        <h2>🩺 四燈號健診</h2>
        {showDaily && (
          <span className={`light ${LIGHT_CLASS[health.total_light] || 'yellow'}`} style={{ fontSize: 12 }}>
            日 {health.total_light} {health.total_score.toFixed(0)}分
          </span>
        )}
        {showWeekly && (
          <span className={`light ${LIGHT_CLASS[weeklyHealth.total_light] || 'yellow'}`} style={{ fontSize: 12 }}>
            週 {weeklyHealth.total_light} {weeklyHealth.total_score.toFixed(0)}分
          </span>
        )}
        {showMonthly && (
          <span className={`light ${LIGHT_CLASS[monthlyHealth.total_light] || 'yellow'}`} style={{ fontSize: 12 }}>
            月 {monthlyHealth.total_light} {monthlyHealth.total_score.toFixed(0)}分
          </span>
        )}
      </div>

      {[showDaily && { key: 'daily', label: '📅 日線級別', data: health },
        showWeekly && { key: 'weekly', label: '📅 週線級別', data: weeklyHealth },
        showMonthly && { key: 'monthly', label: '📅 月線級別', data: monthlyHealth },
      ].filter(Boolean).map((section: any, idx: number) => (
        <div key={section.key} style={idx > 0 ? { borderTop: '1px solid var(--border)', paddingTop: 10, marginTop: 12 } : {}}>
          <div className="text-dim" style={{ fontSize: 11, marginBottom: 6 }}>{section.label}</div>
          <div className="grid-4">
            {aspects.map(([label, scoreKey, lightKey]) => (
              <div key={section.key + '-' + label} className="stat">
                <div className="label">{label}</div>
                <div className="value" style={{ fontSize: 16 }}>{(section.data[scoreKey] as number).toFixed(0)}</div>
                <div className={`light ${LIGHT_CLASS[section.data[lightKey] as string] || 'yellow'} mt-8`} style={{ fontSize: 11 }}>{(section.data[lightKey] as string)}</div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
