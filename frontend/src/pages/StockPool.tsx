import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { StockPoolRow } from '../types'

function pct(n: number | null, digits = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return `${(n * 100).toFixed(digits)}%`
}

function lightColor(light: string | null): string {
  if (!light) return ''
  if (light.includes('🟢') || light === '🟢') return 'green'
  if (light.includes('🔴') || light === '🔴') return 'red'
  if (light.includes('🟡') || light === '🟡') return 'yellow'
  return ''
}

function rsColor(label: string | null): string {
  if (!label) return ''
  if (label === 'very_strong') return 'green-strong'
  if (label === 'strong') return 'green'
  if (label === 'weak') return 'red'
  if (label === 'very_weak') return 'red-strong'
  return ''
}

export default function StockPool() {
  const [asOf, setAsOf] = useState(() => new Date().toISOString().split('T')[0])
  const [sectorFilter, setSectorFilter] = useState<string>('')

  const overview = useQuery({
    queryKey: ['stock-pool', 'overview', asOf],
    queryFn: () => api.stockPoolOverview(asOf || undefined),
  })

  const crossCompare = useQuery({
    queryKey: ['stock-pool', 'cross-compare', asOf],
    queryFn: () => api.stockPoolCrossCompare(asOf || undefined),
  })

  const sectors = useQuery({
    queryKey: ['stock-pool', 'sectors'],
    queryFn: () => api.stockPoolSectors(),
    staleTime: 1000 * 60 * 60, // 1h
  })

  const rows = overview.data?.rows ?? []
  const sectorsList = useMemo(() => Object.keys(overview.data?.by_sector ?? {}).sort(), [overview.data])
  const filteredRows = useMemo<StockPoolRow[]>(() => {
    if (!sectorFilter) return rows
    return rows.filter((r: StockPoolRow) => (r.sector || '其他') === sectorFilter)
  }, [rows, sectorFilter])

  return (
    <div className="page">
      <div className="page-header">
        <h2>個股池訊號</h2>
        <div className="filters">
          <label>
            日期：
            <input
              type="date"
              value={asOf}
              onChange={e => setAsOf(e.target.value)}
              placeholder="留空 = 今日"
            />
          </label>
          <label>
            族群：
            <select value={sectorFilter} onChange={e => setSectorFilter(e.target.value)}>
              <option value="">全部</option>
              {sectorsList.map(s => (
                <option key={s} value={s}>
                  {s} ({(overview.data?.by_sector[s] ?? []).length})
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {overview.isLoading && <div className="text-muted">載入中…</div>}
      {overview.error && <div className="error">載入失敗</div>}

      {overview.data && (
        <>
          <section className="summary-cards">
            <div className="card">
              <div className="card-title">大盤狀態</div>
              <div className="metric-big">{overview.data.market_state ?? '—'}</div>
              <div className="text-muted">觀察清單 {overview.data.pool_size} 檔</div>
            </div>
            <div className="card">
              <div className="card-title">族群數</div>
              <div className="metric-big">{sectorsList.length}</div>
              <div className="text-muted">{sectorsList.join('、')}</div>
            </div>
            <div className="card">
              <div className="card-title">順勢股數</div>
              <div className="metric-big">{overview.data.cross_compare.consistent_count}</div>
              <div className="text-muted">個股方向與大盤一致</div>
            </div>
            <div className="card">
              <div className="card-title">逆勢股數</div>
              <div className="metric-big">{overview.data.cross_compare.inconsistent_count}</div>
              <div className="text-muted">個股方向與大盤相異</div>
            </div>
          </section>

          <section className="cross-compare">
            <h3>大盤 vs 個股 交叉比對</h3>
            {crossCompare.data && (
              <div className="cross-grid">
                <div>
                  <strong>順勢 ({crossCompare.data.consistent_count})</strong>
                  <div className="text-muted">{crossCompare.data.consistent_stocks.join('、') || '—'}</div>
                </div>
                <div>
                  <strong>逆勢 ({crossCompare.data.inconsistent_count})</strong>
                  <div className="text-muted">{crossCompare.data.inconsistent_stocks.join('、') || '—'}</div>
                </div>
                <div>
                  <strong>逆勢強勢 ({crossCompare.data.contrarian_stocks.length})</strong>
                  <div className="text-muted">{crossCompare.data.contrarian_stocks.join('、') || '—'}</div>
                </div>
                <div>
                  <strong>無資料 ({crossCompare.data.no_data_count})</strong>
                  <div className="text-muted">{crossCompare.data.no_data_count > 0 ? '(略)' : '—'}</div>
                </div>
              </div>
            )}
          </section>

          <section className="pool-table">
            <h3>個股清單</h3>
            <table className="data-table">
              <thead>
                <tr>
                  <th>代碼</th>
                  <th>名稱</th>
                  <th>族群</th>
                  <th>健康燈號</th>
                  <th>基本面</th>
                  <th>籌碼</th>
                  <th>技術</th>
                  <th>估值</th>
                  <th>總分</th>
                  <th>訊號</th>
                  <th>共識</th>
                  <th>RS 5d</th>
                  <th>RS 20d</th>
                  <th>RS 60d</th>
                  <th>RS 綜合</th>
                  <th>順勢?</th>
                </tr>
              </thead>
              <tbody>
                {filteredRows.map(r => (
                  <tr key={r.stock_id}>
                    <td>{r.stock_id}</td>
                    <td>{r.name}</td>
                    <td>{r.sector ?? '—'}</td>
                    <td className={lightColor(r.health_light)}>{r.health_light ?? '—'}</td>
                    <td className={lightColor(r.fundamental_light)}>{r.fundamental_light ?? '—'}</td>
                    <td className={lightColor(r.institutional_light)}>{r.institutional_light ?? '—'}</td>
                    <td className={lightColor(r.technical_light)}>{r.technical_light ?? '—'}</td>
                    <td className={lightColor(r.valuation_light)}>{r.valuation_light ?? '—'}</td>
                    <td>{r.total_score?.toFixed(1) ?? '—'}</td>
                    <td>
                      <span className="bullish">{r.bullish_count ?? 0}</span>
                      /
                      <span className="bearish">{r.bearish_count ?? 0}</span>
                    </td>
                    <td>{r.consensus ?? '—'}</td>
                    <td className={rsColor(r.rs_label)}>{pct(r.rs_5d)}</td>
                    <td>{pct(r.rs_20d)}</td>
                    <td>{pct(r.rs_60d)}</td>
                    <td className={rsColor(r.rs_label)}>
                      {pct(r.rs_composite)} ({r.rs_label ?? '—'})
                    </td>
                    <td>
                      {r.market_consistent === true && '✓'}
                      {r.market_consistent === false && '✗'}
                      {r.market_consistent === null && '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          {sectors.data && (
            <section className="sector-section">
              <h3>族群對應 ({sectors.data.length} 檔)</h3>
              <ul className="sector-list">
                {sectors.data.map((s: { stock_id: string; name: string; sector: string }) => (
                  <li key={s.stock_id}>
                    <code>{s.stock_id}</code> {s.name} — <em>{s.sector}</em>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </div>
  )
}