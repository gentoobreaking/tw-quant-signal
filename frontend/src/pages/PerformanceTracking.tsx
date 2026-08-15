import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { PerformanceAgg } from '../types'

const HORIZONS = [
  { value: 1, label: '1 日' },
  { value: 3, label: '3 日' },
  { value: 5, label: '5 日' },
  { value: 10, label: '10 日' },
]

const DAYS_OPTIONS = [7, 14, 30, 60, 90, 180, 365]

const MARKET_STATES = [
  { value: '', label: '全部' },
  { value: 'bull', label: '多頭' },
  { value: 'bear', label: '空頭' },
  { value: 'range', label: '盤整' },
]

function pct(n: number, digits = 2): string {
  return `${(n * 100).toFixed(digits)}%`
}

function fmtNum(n: number, digits = 0): string {
  return n.toFixed(digits)
}

interface AggCardProps {
  title: string
  stats: PerformanceAgg | null
  loading: boolean
}

function AggCard({ title, stats, loading }: AggCardProps) {
  if (loading) {
    return (
      <div className="card">
        <div className="card-title">{title}</div>
        <div className="text-muted">載入中…</div>
      </div>
    )
  }
  if (!stats || stats.triggers === 0) {
    return (
      <div className="card">
        <div className="card-title">{title}</div>
        <div className="text-muted">無觸發資料</div>
      </div>
    )
  }
  const winColor = stats.win_rate >= 0.5 ? 'text-green' : 'text-red'
  return (
    <div className="card">
      <div className="card-title">{title}</div>
      <div className="kpi-grid">
        <div className="kpi">
          <div className="kpi-label">觸發</div>
          <div className="kpi-value">{stats.triggers}</div>
        </div>
        <div className="kpi">
          <div className="kpi-label">勝率</div>
          <div className={`kpi-value ${winColor}`}>{pct(stats.win_rate)}</div>
        </div>
        <div className="kpi">
          <div className="kpi-label">平均淨報酬</div>
          <div className={`kpi-value ${stats.avg_return >= 0 ? 'text-green' : 'text-red'}`}>
            {pct(stats.avg_return)}
          </div>
        </div>
        <div className="kpi">
          <div className="kpi-label">盈虧比</div>
          <div className="kpi-value">{fmtNum(stats.profit_ratio, 2)}</div>
        </div>
        <div className="kpi">
          <div className="kpi-label">平均獲利</div>
          <div className="kpi-value text-green">{pct(stats.avg_win)}</div>
        </div>
        <div className="kpi">
          <div className="kpi-label">平均虧損</div>
          <div className="kpi-value text-red">{pct(stats.avg_loss)}</div>
        </div>
        <div className="kpi">
          <div className="kpi-label">最大 DD</div>
          <div className="kpi-value">{pct(stats.max_dd)}</div>
        </div>
        <div className="kpi">
          <div className="kpi-label">最長連虧</div>
          <div className="kpi-value">{stats.max_consecutive_losses}</div>
        </div>
        <div className="kpi">
          <div className="kpi-label">期望值</div>
          <div className={`kpi-value ${stats.expectancy >= 0 ? 'text-green' : 'text-red'}`}>
            {pct(stats.expectancy)}
          </div>
        </div>
      </div>
    </div>
  )
}

export default function PerformanceTracking() {
  const [days, setDays] = useState(30)
  const [horizon, setHorizon] = useState(5)
  const [marketState, setMarketState] = useState('')

  const overviewQ = useQuery({
    queryKey: ['perf-overview', days, horizon],
    queryFn: () => api.performanceOverview(days, horizon),
    refetchInterval: 60_000,
  })

  const rulesQ = useQuery({
    queryKey: ['perf-rules', days, horizon, marketState],
    queryFn: () => api.performanceRules(days, horizon, marketState || undefined),
    refetchInterval: 60_000,
  })

  const logsQ = useQuery({
    queryKey: ['perf-logs', days],
    queryFn: () => api.performanceLogs(days),
    refetchInterval: 60_000,
  })

  const overview = overviewQ.data ?? null
  const rulesResp = rulesQ.data ?? null
  const logs = logsQ.data ?? []

  // Map overview (API) to the PerformanceAgg shape for AggCard
  const overviewAgg: PerformanceAgg | null = overview
    ? {
        triggers: overview.total_triggers,
        wins: overview.by_state ? Math.round(overview.total_triggers * overview.win_rate) : 0,
        losses: overview.by_state
          ? Math.round(overview.total_triggers * (1 - overview.win_rate))
          : 0,
        win_rate: overview.win_rate,
        avg_return: overview.avg_return,
        avg_win: overview.avg_win,
        avg_loss: overview.avg_loss,
        profit_ratio: overview.profit_ratio,
        max_dd: overview.max_dd,
        max_consecutive_losses: overview.consecutive_losses,
        expectancy: overview.expectancy,
      }
    : null

  const ruleEntries = rulesResp?.rules ? Object.entries(rulesResp.rules) : []

  return (
    <div className="performance-page">
      <h2>訊號績效追蹤（T019）</h2>
      <div className="filter-row">
        <label>
          區間：
          <select value={days} onChange={e => setDays(Number(e.target.value))}>
            {DAYS_OPTIONS.map(d => <option key={d} value={d}>{d} 日</option>)}
          </select>
        </label>
        <label>
          持有期：
          <select value={horizon} onChange={e => setHorizon(Number(e.target.value))}>
            {HORIZONS.map(h => <option key={h.value} value={h.value}>{h.label}</option>)}
          </select>
        </label>
        <label>
          市場狀態：
          <select value={marketState} onChange={e => setMarketState(e.target.value)}>
            {MARKET_STATES.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
          </select>
        </label>
      </div>

      <div className="overview-row">
        <AggCard
          title={`整體（最近 ${days} 日，${horizon} 日持有期）`}
          stats={overviewAgg}
          loading={overviewQ.isLoading}
        />
        {overview?.by_state && Object.keys(overview.by_state).length > 0 && (
          <div className="card">
            <div className="card-title">依市場狀態分類</div>
            <table className="table-compact">
              <thead>
                <tr>
                  <th>狀態</th>
                  <th>觸發</th>
                  <th>勝率</th>
                  <th>平均淨報酬</th>
                  <th>最大 DD</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(overview.by_state).map(([state, s]) => (
                  <tr key={state}>
                    <td>{state}</td>
                    <td>{s.triggers}</td>
                    <td className={s.win_rate >= 0.5 ? 'text-green' : 'text-red'}>{pct(s.win_rate)}</td>
                    <td className={s.avg_return >= 0 ? 'text-green' : 'text-red'}>{pct(s.avg_return)}</td>
                    <td>{pct(s.max_dd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card">
        <div className="card-title">規則績效明細</div>
        {rulesQ.isLoading ? (
          <div className="text-muted">載入中…</div>
        ) : ruleEntries.length === 0 ? (
          <div className="text-muted">沒有觸發紀錄或選擇的市場狀態下無資料</div>
        ) : (
          <table className="table-data">
            <thead>
              <tr>
                <th>規則 ID</th>
                <th>名稱</th>
                <th>類型</th>
                <th>觸發</th>
                <th>勝</th>
                <th>敗</th>
                <th>勝率</th>
                <th>平均淨報酬</th>
                <th>盈虧比</th>
                <th>最大 DD</th>
                <th>連虧</th>
                <th>期望值</th>
              </tr>
            </thead>
            <tbody>
              {ruleEntries.map(([rid, info]) => {
                const s = info.stats
                return (
                  <tr key={rid}>
                    <td className="mono">{rid}</td>
                    <td>{info.name}</td>
                    <td><span className={`tag tag-${info.type}`}>{info.type}</span></td>
                    <td>{s.triggers}</td>
                    <td className="text-green">{s.wins}</td>
                    <td className="text-red">{s.losses}</td>
                    <td className={s.win_rate >= 0.5 ? 'text-green' : 'text-red'}>{pct(s.win_rate)}</td>
                    <td className={s.avg_return >= 0 ? 'text-green' : 'text-red'}>{pct(s.avg_return)}</td>
                    <td>{fmtNum(s.profit_ratio, 2)}</td>
                    <td>{pct(s.max_dd)}</td>
                    <td>{s.max_consecutive_losses}</td>
                    <td className={s.expectancy >= 0 ? 'text-green' : 'text-red'}>{pct(s.expectancy)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>

      <div className="card">
        <div className="card-title">觸發紀錄（前 {logs.length} 筆）</div>
        {logsQ.isLoading ? (
          <div className="text-muted">載入中…</div>
        ) : logs.length === 0 ? (
          <div className="text-muted">無觸發紀錄</div>
        ) : (
          <div className="logs-scroll">
            <table className="table-data">
              <thead>
                <tr>
                  <th>觸發日</th>
                  <th>規則</th>
                  <th>標的</th>
                  <th>市況</th>
                  <th>收盤</th>
                  <th>1d</th>
                  <th>3d</th>
                  <th>5d</th>
                  <th>10d</th>
                  <th>檢查日</th>
                </tr>
              </thead>
              <tbody>
                {logs.slice(0, 100).map(l => (
                  <tr key={l.id}>
                    <td>{l.trigger_date}</td>
                    <td className="mono">{l.rule_id}</td>
                    <td className="mono">{l.stock_id}</td>
                    <td>{l.market_state ?? '-'}</td>
                    <td>{l.close_at_trigger?.toFixed(1) ?? '-'}</td>
                    <td className={cellClass(l.after_1d_return)}>{fmtReturn(l.after_1d_return)}</td>
                    <td className={cellClass(l.after_3d_return)}>{fmtReturn(l.after_3d_return)}</td>
                    <td className={cellClass(l.after_5d_return)}>{fmtReturn(l.after_5d_return)}</td>
                    <td className={cellClass(l.after_10d_return)}>{fmtReturn(l.after_10d_return)}</td>
                    <td>{l.inspection_date ?? '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {rulesResp?.markdown_table && (
        <div className="card">
          <div className="card-title">Markdown 報告</div>
          <pre className="markdown-pre">{rulesResp.markdown_table}</pre>
        </div>
      )}
    </div>
  )
}

function fmtReturn(v: number | null): string {
  if (v == null) return '-'
  return `${(v * 100).toFixed(2)}%`
}

function cellClass(v: number | null): string {
  if (v == null) return ''
  return v >= 0 ? 'text-green' : 'text-red'
}