import type { RiskMetric } from '../types'

const LEVEL_LABEL: Record<string, string> = {
  severe: '🔴 嚴重', warning: '🟠 警告', caution: '🟡 注意', normal: '🟢 正常',
}

export default function RiskCard({ risk }: { risk: RiskMetric | null | undefined }) {
  if (!risk) return null
  return (
    <div className="card">
      <div className="flex-between mb-8">
        <h2>⚠️ 風險監控</h2>
        <span className={`risk-badge ${risk.risk_level}`}>{LEVEL_LABEL[risk.risk_level] || risk.risk_level} ({risk.risk_score}分)</span>
      </div>
      <div className="card-row">
        {risk.vol_ratio != null && (
          <div className="stat">
            <div className="value" style={{ color: risk.vol_ratio > 1.3 ? 'var(--orange)' : 'var(--text)' }}>{risk.vol_ratio.toFixed(2)}x</div>
            <div className="label">波動率倍數</div>
          </div>
        )}
        {risk.atr_pct != null && (
          <div className="stat">
            <div className="value">{(risk.atr_pct * 100).toFixed(1)}%</div>
            <div className="label">ATR</div>
          </div>
        )}
        {risk.max_drawdown != null && (
          <div className="stat">
            <div className="value" style={{ color: risk.max_drawdown > 0.15 ? 'var(--red)' : 'var(--text)' }}>{(risk.max_drawdown * 100).toFixed(1)}%</div>
            <div className="label">最大回撤</div>
          </div>
        )}
        {risk.signal_conflict ? (
          <div className="stat">
            <div className="value" style={{ color: 'var(--orange)' }}>⚠</div>
            <div className="label">多空衝突</div>
          </div>
        ) : null}
      </div>
      <div className="card-row mt-8">
        {risk.stop_loss_atr != null && (
          <div className="stat" style={{ minWidth: 100 }}>
            <div className="value" style={{ fontSize: 18 }}>{risk.stop_loss_atr.toFixed(1)}</div>
            <div className="label">停損參考(ATR)</div>
          </div>
        )}
        {risk.stop_loss_ma != null && (
          <div className="stat" style={{ minWidth: 100 }}>
            <div className="value" style={{ fontSize: 18 }}>{risk.stop_loss_ma.toFixed(1)}</div>
            <div className="label">停損參考(MA)</div>
          </div>
        )}
      </div>
    </div>
  )
}
