import { useState, useCallback, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Rule } from '../types'

const TYPE_MAP: Record<string, Record<string, string>> = {
  eq: { bullish: '==', bearish: '!=', gt: '>', lt: '<', gte: '>=', lte: '<=', in: '∈' },
}

function RuleEditor({ rule, onChange }: { rule: Rule; onChange: (r: Rule) => void }) {
  const [expanded, setExpanded] = useState(false)

  const update = (key: string, value: any) => onChange({ ...rule, [key]: value })

  const allConds = (rule.conditions as any)?.all
  const condEntries = Array.isArray(allConds)
    ? allConds.map((c: any, i: number) => (
        <div key={i} className="text-dim" style={{ fontSize: 12, padding: '2px 0' }}>
          <code style={{ color: 'var(--blue)' }}>{c.feature}</code>
          {' '}{TYPE_MAP.eq[c.operator] || c.operator}{' '}
          <code style={{ color: 'var(--orange)' }}>{Array.isArray(c.value) ? c.value.join(', ') : String(c.value)}</code>
        </div>
      ))
    : null

  return (
    <div className="rule-card" style={{ borderLeft: `3px solid ${rule.type === 'bullish' ? 'var(--green)' : rule.type === 'bearish' ? 'var(--red)' : 'var(--orange)'}` }}>
      <div className="header">
        <div className="flex gap-8" style={{ alignItems: 'center' }}>
          <span className="id">{rule.id}</span>
          <span className={`light ${rule.type === 'bullish' ? 'green' : rule.type === 'bearish' ? 'red' : 'yellow'}`}>{rule.type}</span>
          <span style={{ fontSize: 13 }}>{rule.name}</span>
        </div>
        <div className="flex gap-8">
          <span className="text-dim" style={{ fontSize: 11 }}>{rule._source}</span>
          <button className="btn btn-sm" onClick={() => setExpanded(!expanded)}>{expanded ? '收合' : '編輯'}</button>
        </div>
      </div>
      <div className="text-dim" style={{ fontSize: 12, marginTop: 4 }}>{rule.description}</div>
      {expanded && (
        <div style={{ marginTop: 8 }}>
          <div className="form-row">
            <div>
              <label>規則名稱</label>
              <input value={rule.name} onChange={e => update('name', e.target.value)} />
            </div>
            <div>
              <label>類型</label>
              <select value={rule.type} onChange={e => update('type', e.target.value)}>
                <option value="bullish">bullish</option>
                <option value="bearish">bearish</option>
                <option value="neutral">neutral</option>
              </select>
            </div>
          </div>
          <div className="mb-8">
            <label>描述</label>
            <textarea rows={2} value={rule.description} onChange={e => update('description', e.target.value)} />
          </div>
          <div className="mb-8">
            <label>失效條件</label>
            <input value={rule.failure_condition} onChange={e => update('failure_condition', e.target.value)} />
          </div>
          <div className="mb-8">
            <label>標籤</label>
            <input value={rule.tags?.join(', ') || ''} onChange={e => update('tags', e.target.value.split(',').map(t => t.trim()))} />
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>
            <label>條件 ({Array.isArray(allConds) ? allConds.length : 0} 條)</label>
            {condEntries}
          </div>
        </div>
      )}
    </div>
  )
}

export default function RulesManagement() {
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<string>('bullish')
  const [rules, setRules] = useState<Rule[]>([])
  const [config, setConfig] = useState<{ watch_stocks: string[] }>({ watch_stocks: [] })
  const [toast, setToast] = useState<{ msg: string; type: 'success' | 'error' } | null>(null)

  const showToast = useCallback((msg: string, type: 'success' | 'error' = 'success') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 2500)
  }, [])

  const { isLoading: rulesLoading } = useQuery({
    queryKey: ['rules'],
    queryFn: async () => {
      const data = await api.rules()
      setRules(data)
      return data
    },
  })

  const { isLoading: configLoading } = useQuery({
    queryKey: ['config'],
    queryFn: async () => {
      const data = await api.config()
      setConfig(data)
      return data
    },
  })

  const saveRulesMut = useMutation({
    mutationFn: (updated: Rule[]) => api.updateRules(updated),
    onSuccess: () => {
      showToast('規則已儲存')
      queryClient.invalidateQueries({ queryKey: ['rules'] })
    },
    onError: () => showToast('儲存失敗', 'error'),
  })

  const saveConfigMut = useMutation({
    mutationFn: (cfg: { watch_stocks: string[] }) => api.updateConfig(cfg),
    onSuccess: () => {
      showToast('設定已儲存')
      queryClient.invalidateQueries({ queryKey: ['config'] })
    },
    onError: () => showToast('儲存失敗', 'error'),
  })

  const filtered = rules.filter(r => r.type === tab || (tab === 'all' ? true : false))

  const updateRule = (index: number, updated: Rule) => {
    const copy = [...rules]
    copy[index] = updated
    setRules(copy)
  }

  const configStocksStr = config.watch_stocks?.join(', ') || ''

  return (
    <div>
      {toast && <div className={`toast ${toast.type}`}>{toast.msg}</div>}

      {/* Config section */}
      <div className="card">
        <div className="flex-between mb-8">
          <h2>⚙️ 設定</h2>
          <button
            className="btn btn-primary btn-sm"
            onClick={() => saveConfigMut.mutate(config)}
            disabled={saveConfigMut.isPending}
          >
            {saveConfigMut.isPending ? '儲存中...' : '儲存設定'}
          </button>
        </div>
        <div className="form-row">
          <div>
            <label>觀察標的 (逗號分隔)</label>
            <input
              value={configStocksStr}
              onChange={e => setConfig({ ...config, watch_stocks: e.target.value.split(',').map(s => s.trim()).filter(Boolean) })}
              placeholder="2330, 0050, 2308"
            />
          </div>
        </div>
      </div>

      {/* Rules section */}
      <div className="card">
        <div className="flex-between mb-8">
          <h2>📜 規則列表 (共 {rules.length} 條)</h2>
          <button
            className="btn btn-primary btn-sm"
            onClick={() => saveRulesMut.mutate(rules)}
            disabled={saveRulesMut.isPending}
          >
            {saveRulesMut.isPending ? '儲存中...' : '儲存全部規則'}
          </button>
        </div>

        <div className="rule-tabs">
          {[
            { key: 'bullish', label: '📈 偏多' },
            { key: 'neutral', label: '➡️ 中性' },
            { key: 'bearish', label: '📉 偏空' },
            { key: 'all', label: '全部' },
          ].map(t => (
            <div
              key={t.key}
              className={`rule-tab ${tab === t.key ? 'active' : ''}`}
              onClick={() => setTab(t.key)}
            >
              {t.label} ({rules.filter(r => t.key === 'all' ? true : r.type === t.key).length})
            </div>
          ))}
        </div>

        {rulesLoading ? (
          <div className="empty">載入中...</div>
        ) : filtered.length === 0 ? (
          <div className="empty">無規則</div>
        ) : (
          filtered.map((rule, i) => {
            const globalIndex = rules.findIndex(r => r.id === rule.id)
            return <RuleEditor key={rule.id} rule={rule} onChange={(r) => updateRule(globalIndex, r)} />
          })
        )}
      </div>
    </div>
  )
}
