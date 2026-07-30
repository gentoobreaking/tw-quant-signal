import GaugeChart from './GaugeChart'

interface SubIndicator {
  name: string
  weight: string
  scoring: string
}

const ASPECTS: Record<string, { label: string; sub: SubIndicator[] }> = {
  fundamental: {
    label: '基本面',
    sub: [
      { name: 'EPS 成長率', weight: '40%', scoring: '近4季 vs 前4季：≥20%→100, ≥10%→70, ≥0%→40, <0%→0' },
      { name: '營收成長率', weight: '30%', scoring: '近季 vs 去年同期：≥15%→100, ≥5%→70, ≥0%→40, <0%→0' },
      { name: '毛利率趨勢', weight: '30%', scoring: '近季 vs 前季：上升→100, 持平→50, 下降→0' },
    ],
  },
  institutional: {
    label: '籌碼面',
    sub: [
      { name: '外資持股占比', weight: '40%', scoring: '外資近5日淨買超/流通股數：>0.1%→100, >0%→60, >-0.1%→30, ≤-0.1%→0' },
      { name: '投信持股占比', weight: '30%', scoring: '投信近5日淨買超/流通股數：>0.05%→100, >0%→60, >-0.05%→30, ≤-0.05%→0' },
      { name: '券資比', weight: '30%', scoring: '融券/融資：>20%→100, >10%→70, >5%→40, ≤5%→0' },
    ],
  },
  technical: {
    label: '技術面',
    sub: [
      { name: '均線排列', weight: '40%', scoring: 'MA5>MA20>MA60→多頭100, MA5<MA20<MA60→空頭0, 其他→中立50' },
      { name: 'RSI 指標', weight: '30%', scoring: 'RSI>70→過熱0, RSI>50→偏多100, RSI>30→中立50, ≤30→超賣0' },
      { name: '布林通道', weight: '30%', scoring: '價格>上軌→過熱0, 價格於上軌與中軌間→偏多100, 中軌與下軌間→偏空0, <下軌→超賣100' },
    ],
  },
  valuation: {
    label: '估值面',
    sub: [
      { name: '本益比', weight: '40%', scoring: 'PE vs 5年均值：<80%→低估100, <100%→偏低70, <120%→偏高30, ≥120%→高估0' },
      { name: '股價淨值比', weight: '30%', scoring: 'PB vs 5年均值：<80%→低估100, <100%→偏低70, <120%→偏高30, ≥120%→高估0' },
      { name: '殖利率', weight: '30%', scoring: 'DY vs 5年均值：>120%→高殖利100, >100%→偏高70, >80%→偏低30, ≤80%→低殖利0' },
    ],
  },
}

export default function HealthAspectDetail({ stockId, health }: { stockId: string; health: Record<string, any> | null }) {
  if (!health) return null

  return (
    <div className="card">
      <h2>🔍 四面向健診細項</h2>
      <div className="grid-4 mt-8" style={{ marginBottom: 16 }}>
        {(['fundamental', 'institutional', 'technical', 'valuation'] as const).map(key => (
          <GaugeChart
            key={key}
            score={health[`${key}_score`] ?? 0}
            light={health[`${key}_light`] ?? '🟡'}
            label={ASPECTS[key].label}
            size={100}
          />
        ))}
      </div>
      {(['fundamental', 'institutional', 'technical', 'valuation'] as const).map(aspectKey => {
        const aspect = ASPECTS[aspectKey]
        return (
          <details key={aspectKey} style={{ marginBottom: 8 }}>
            <summary style={{ cursor: 'pointer', fontSize: 13, fontWeight: 600, padding: '8px 0', color: 'var(--text)' }}>
              {aspect.label} — {Math.round(health[`${aspectKey}_score`] ?? 0)} 分
            </summary>
            <table style={{ fontSize: 12 }}>
              <thead>
                <tr>
                  <th style={{ width: '25%' }}>指標</th>
                  <th style={{ width: '10%' }}>權重</th>
                  <th style={{ width: '65%' }}>計分方式</th>
                </tr>
              </thead>
              <tbody>
                {aspect.sub.map(sub => (
                  <tr key={sub.name}>
                    <td>{sub.name}</td>
                    <td>{sub.weight}</td>
                    <td className="text-dim" style={{ fontSize: 11 }}>{sub.scoring}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        )
      })}
    </div>
  )
}
