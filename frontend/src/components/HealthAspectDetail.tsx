import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import GaugeChart from './GaugeChart'

const ASPECT_KEYS = ['fundamental', 'institutional', 'technical', 'valuation'] as const

const PCT_KEYS = new Set(['eps_growth', 'revenue_yoy', 'foreign_ratio', 'sity_ratio', 'margin_ratio', 'dividend_yield'])

function fmt(n: number, d: number = 2) {
  return n.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d })
}

function renderExpression(subKey: string, rs: Record<string, any> | undefined): string {
  if (!rs) return '-'
  const inputs = rs.inputs
  const val = rs.value

  if (subKey === 'eps_growth' && inputs?.latest_eps != null && inputs?.prev_eps != null) {
    const c = inputs.latest_eps, p = inputs.prev_eps
    return `(${fmt(c)} - ${fmt(p)}) / ${fmt(p)} × 100% = ${val != null ? fmt(val) + '%' : '-'}`
  }
  if (subKey === 'revenue_yoy' && inputs?.latest_revenue != null && inputs?.prev_revenue != null) {
    const lr = inputs.latest_revenue, pr = inputs.prev_revenue
    return `(${lr.toLocaleString()} - ${pr.toLocaleString()}) / ${pr.toLocaleString()} × 100% = ${val != null ? fmt(val) + '%' : '-'}`
  }
  if (subKey === 'gross_margin' && inputs?.latest_gm != null && inputs?.prev_gm != null) {
    return `本期${fmt(inputs.latest_gm)}% - 上期${fmt(inputs.prev_gm)}% = ${inputs.latest_gm - inputs.prev_gm >= 0 ? '+' : ''}${fmt(inputs.latest_gm - inputs.prev_gm)}% → ${val != null ? fmt(val, 0) + '分' : '-'}`
  }
  if ((subKey === 'foreign_ratio' || subKey === 'sity_ratio') && inputs?.buy_5d != null && inputs?.vol_ma20 != null) {
    const b = inputs.buy_5d, v = inputs.vol_ma20
    return `${b.toLocaleString()} / (${v.toLocaleString()} × 5) × 100% = ${val != null ? fmt(val) + '%' : '-'}`
  }
  if (subKey === 'margin_ratio' && inputs?.margin_balance != null && inputs?.short_balance != null) {
    const mb = inputs.margin_balance, sb = Math.round(inputs.short_balance / 1000)
    return `融券${sb.toLocaleString()}張 / 融資${mb.toLocaleString()}張 × 100% = ${val != null ? fmt(val) + '%' : '-'}`
  }
  if (subKey === 'ma_alignment' && inputs?.ma5 != null && inputs?.ma20 != null && inputs?.ma60 != null) {
    const { ma5, ma20, ma60 } = inputs
    return `MA5=${fmt(ma5, 0)}, MA20=${fmt(ma20, 0)}, MA60=${fmt(ma60, 0)} → ${val ?? '-'}`
  }
  if (subKey === 'rsi14' && inputs?.rsi != null) {
    return `RSI=${fmt(inputs.rsi)}`
  }
  if (subKey === 'bb_position' && inputs?.close != null && inputs?.bb_upper != null && inputs?.bb_middle != null && inputs?.bb_lower != null) {
    const { close, bb_upper, bb_middle, bb_lower } = inputs
    return `收=${fmt(close, 0)}, 上=${fmt(bb_upper, 0)}, 中=${fmt(bb_middle, 0)}, 下=${fmt(bb_lower, 0)} → ${val ?? '-'}`
  }
  if (subKey === 'dividend_yield' && inputs?.dividend_yield != null && inputs?.close != null) {
    const dy = inputs.dividend_yield * 100, c = inputs.close
    return `股利/${fmt(c, 0)} × 100% = ${fmt(dy)}%`
  }
  // fallback
  return `${val != null ? (typeof val === 'number' ? fmt(val) : val) : '-'}`
}

export default function HealthAspectDetail({ stockId, health }: { stockId: string; health: Record<string, any> | null }) {
  const { data: hcConfig } = useQuery({
    queryKey: ['health-check-config'],
    queryFn: () => api.healthCheckConfig(),
    staleTime: 60_000,
  })

  if (!health) return null

  const aspects = (hcConfig?.aspects || {}) as Record<string, any>

  return (
    <div className="card">
      <h2>🔍 四面向健診細項</h2>
      <div className="grid-4 mt-8" style={{ marginBottom: 16 }}>
        {ASPECT_KEYS.map(key => (
          <GaugeChart
            key={key}
            score={health[`${key}_score`] ?? 0}
            light={health[`${key}_light`] ?? '🟡'}
            label={aspects[key]?.label || key}
            size={100}
          />
        ))}
      </div>
      {ASPECT_KEYS.map(aspectKey => {
        const aspect = aspects[aspectKey]
        if (!aspect) return null
        return (
          <details key={aspectKey} style={{ marginBottom: 8 }}>
            <summary style={{ cursor: 'pointer', fontSize: 13, fontWeight: 600, padding: '8px 0', color: 'var(--text)' }}>
              {aspect.label} — {Math.round(health[`${aspectKey}_score`] ?? 0)} 分
            </summary>
              <table style={{ fontSize: 12 }}>
                <thead>
                  <tr>
                    <th style={{ width: '15%' }}>指標</th>
                    <th style={{ width: '7%' }}>權重</th>
                    <th style={{ width: '22%' }}>計分方式</th>
                    <th style={{ width: '22%' }}>計算公式</th>
                    <th style={{ width: '34%' }}>結果</th>
                  </tr>
                </thead>
                <tbody>
                  {(aspect.sub || []).map((sub: any) => {
                    const runtimeSub = health.details?.[aspectKey]?.sub?.[sub.key]
                    const score = runtimeSub?.score
                    const expr = renderExpression(sub.key, runtimeSub)
                    return (
                      <tr key={sub.key || sub.name}>
                        <td>{sub.name}</td>
                        <td>{sub.weight}%</td>
                        <td className="text-dim" style={{ fontSize: 11 }}>{sub.scoring}</td>
                        <td className="text-dim" style={{ fontSize: 11, fontFamily: 'monospace' }}>{sub.formula || '-'}</td>
                        <td style={{ fontSize: 11, fontFamily: 'monospace' }}>{expr} → {score != null ? `${score}分` : '-'}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
          </details>
        )
      })}
    </div>
  )
}
