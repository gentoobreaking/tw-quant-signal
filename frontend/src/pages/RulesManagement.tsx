import { useState, useEffect, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Rule } from '../types'

const OP_LABELS: Record<string, string> = {
  eq: '==', ne: '!=', gt: '>', lt: '<', gte: '>=', lte: '<=', in: '∈',
}

const KNOWN_FEATURES = [
  'close_vs_ma20', 'close_vs_ma60', 'ma_alignment',
  'rsi_signal', 'bb_position', 'volume_ratio',
  'foreign_5d_trend', 'sity_5d_trend', 'dealer_net_1d',
  'pe_signal', 'pb_signal', 'dy_signal',
  'index_vs_ma20', 'index_vs_ma60', 'market_breadth',
  'beta_5d',
]

function CondRow({ cond, onChange, onDelete }: {
  cond: Record<string, any>
  onChange: (c: Record<string, any>) => void
  onDelete: () => void
}) {
  const valStr = Array.isArray(cond.value) ? cond.value.join(', ') : String(cond.value ?? '')

  return (
    <div className="form-row" style={{ alignItems: 'center', marginBottom: 6 }}>
      <div style={{ flex: 2 }}>
        <input
          list="feature-list" value={cond.feature || ''}
          onChange={e => onChange({ ...cond, feature: e.target.value })}
          placeholder="feature"
          style={{ fontSize: 12 }}
        />
      </div>
      <div style={{ flex: 1 }}>
        <select value={cond.operator || 'eq'} onChange={e => onChange({ ...cond, operator: e.target.value })} style={{ fontSize: 12 }}>
          {Object.entries(OP_LABELS).map(([k, v]) => <option key={k} value={k}>{k} ({v})</option>)}
        </select>
      </div>
      <div style={{ flex: 2 }}>
        <input
          value={valStr}
          onChange={e => {
            const parts = e.target.value.split(',').map(s => s.trim()).filter(Boolean)
            onChange({ ...cond, value: parts.length > 1 ? parts : (parts[0] || '') })
          }}
          placeholder="value (逗號分隔多值)"
          style={{ fontSize: 12 }}
        />
      </div>
      <button className="btn btn-sm" onClick={onDelete} style={{ color: 'var(--red)', borderColor: 'transparent', padding: '4px 6px' }}>✕</button>
      <datalist id="feature-list">
        {KNOWN_FEATURES.map(f => <option key={f} value={f} />)}
      </datalist>
    </div>
  )
}

function RuleEditor({ rule, onChange }: { rule: Rule; onChange: (r: Rule) => void }) {
  const [expanded, setExpanded] = useState(false)

  const update = (key: string, value: any) => onChange({ ...rule, [key]: value })

  const allConds: Record<string, any>[] = Array.isArray((rule.conditions as any)?.all)
    ? (rule.conditions as any).all
    : []

  const updateCond = (idx: number, cond: Record<string, any>) => {
    const copy = [...allConds]
    copy[idx] = cond
    update('conditions', { all: copy })
  }
  const deleteCond = (idx: number) => {
    const copy = allConds.filter((_, i) => i !== idx)
    update('conditions', { all: copy })
  }
  const addCond = () => {
    update('conditions', { all: [...allConds, { feature: '', operator: 'eq', value: '' }] })
  }

  const condEntries = allConds.map((c, i) => (
    <CondRow key={i} cond={c} onChange={cond => updateCond(i, cond)} onDelete={() => deleteCond(i)} />
  ))

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
            <div className="flex-between mb-8">
              <label>條件 ({allConds.length} 條)</label>
              <button className="btn btn-sm" onClick={addCond}>+ 新增條件</button>
            </div>
            <div style={{ display: 'flex', gap: 8, fontSize: 11, color: 'var(--text-dim)', padding: '0 4px', marginBottom: 4 }}>
              <span style={{ flex: 2 }}>特徵</span>
              <span style={{ flex: 1 }}>運算</span>
              <span style={{ flex: 2 }}>值</span>
              <span style={{ width: 30 }} />
            </div>
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
  const [configTab, setConfigTab] = useState<'rules' | 'health'>('rules')
  const [rules, setRules] = useState<Rule[]>([])
  const [config, setConfig] = useState<{ watch_stocks: string[] }>({ watch_stocks: [] })
  const [hcConfig, setHcConfig] = useState<Record<string, any>>({})
  const [toast, setToast] = useState<{ msg: string; type: 'success' | 'error' } | null>(null)

  const showToast = useCallback((msg: string, type: 'success' | 'error' = 'success') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 2500)
  }, [])

  const { data: rulesData, isLoading: rulesLoading } = useQuery({
    queryKey: ['rules'],
    queryFn: () => api.rules(),
    staleTime: 0,
  })

  const { data: configData, isLoading: configLoading } = useQuery({
    queryKey: ['config'],
    queryFn: () => api.config(),
    staleTime: 0,
  })

  const { data: hcConfigData } = useQuery({
    queryKey: ['health-check-config'],
    queryFn: () => api.healthCheckConfig(),
    staleTime: 0,
  })

  useEffect(() => { if (rulesData) setRules(rulesData) }, [rulesData])
  useEffect(() => { if (configData) setConfig(configData) }, [configData])
  useEffect(() => { if (hcConfigData) setHcConfig(hcConfigData) }, [hcConfigData])

  const rulesForDisplay = rules.length > 0 ? rules : (rulesData || [])

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

  const saveHcConfigMut = useMutation({
    mutationFn: (cfg: Record<string, any>) => api.updateHealthCheckConfig(cfg),
    onSuccess: () => {
      showToast('健診配置已儲存')
      queryClient.invalidateQueries({ queryKey: ['health-check-config'] })
    },
    onError: () => showToast('儲存失敗', 'error'),
  })

  const filtered = rulesForDisplay.filter(r => r.type === tab || (tab === 'all' ? true : false))

  const updateRule = (index: number, updated: Rule) => {
    const copy = [...rules]
    copy[index] = updated
    setRules(copy)
  }

  const configStocksStr = config.watch_stocks?.join(', ') || ''

  const updateHcWeight = (aspect: string, idx: number, val: number) => {
    const copy = { ...hcConfig }
    if (copy.aspects?.[aspect]?.sub?.[idx]) {
      copy.aspects[aspect].sub[idx].weight = val
      setHcConfig(copy)
    }
  }

  const updateHcScoring = (aspect: string, idx: number, val: string) => {
    const copy = { ...hcConfig }
    if (copy.aspects?.[aspect]?.sub?.[idx]) {
      copy.aspects[aspect].sub[idx].scoring = val
      setHcConfig(copy)
    }
  }

  const updateAspectWeight = (aspect: string, val: number) => {
    const copy = { ...hcConfig }
    copy.aspect_weights = { ...(copy.aspect_weights || {}), [aspect]: val }
    setHcConfig(copy)
  }

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

      {/* Config tab switch */}
      <div className="rule-tabs" style={{ marginTop: 16 }}>
        <div className={`rule-tab ${configTab === 'rules' ? 'active' : ''}`} onClick={() => setConfigTab('rules')}>
          📜 規則引擎
        </div>
        <div className={`rule-tab ${configTab === 'health' ? 'active' : ''}`} onClick={() => setConfigTab('health')}>
          🩺 四燈號健診配置
        </div>
      </div>

      {configTab === 'rules' && (
        <div className="card">
          <div className="flex-between mb-8">
            <h2>📜 規則列表 (共 {rulesForDisplay.length} 條)</h2>
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
                {t.label} ({rulesForDisplay.filter(r => t.key === 'all' ? true : r.type === t.key).length})
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
      )}

      {configTab === 'health' && (
        <HealthCheckConfigEditor
          config={hcConfig}
          onUpdate={setHcConfig}
          onSave={() => saveHcConfigMut.mutate(hcConfig)}
          saving={saveHcConfigMut.isPending}
        />
      )}
    </div>
  )
}

function HealthCheckConfigEditor({ config, onUpdate, onSave, saving }: {
  config: Record<string, any>
  onUpdate: (c: Record<string, any>) => void
  onSave: () => void
  saving: boolean
}) {
  const aspectWeights = config.aspect_weights || {}
  const aspects: Record<string, any> = config.aspects || {}

  const updateWeight = (key: string, val: number) => {
    onUpdate({ ...config, aspect_weights: { ...aspectWeights, [key]: val } })
  }

  const updateSubWeight = (aspectKey: string, subIdx: number, val: number) => {
    const copy = { ...aspects }
    const subs = [...(copy[aspectKey]?.sub || [])]
    subs[subIdx] = { ...subs[subIdx], weight: val }
    copy[aspectKey] = { ...copy[aspectKey], sub: subs }
    onUpdate({ ...config, aspects: copy })
  }

  const updateSubScoring = (aspectKey: string, subIdx: number, val: string) => {
    const copy = { ...aspects }
    const subs = [...(copy[aspectKey]?.sub || [])]
    subs[subIdx] = { ...subs[subIdx], scoring: val }
    copy[aspectKey] = { ...copy[aspectKey], sub: subs }
    onUpdate({ ...config, aspects: copy })
  }

  const updateSubFormula = (aspectKey: string, subIdx: number, val: string) => {
    const copy = { ...aspects }
    const subs = [...(copy[aspectKey]?.sub || [])]
    subs[subIdx] = { ...subs[subIdx], formula: val }
    copy[aspectKey] = { ...copy[aspectKey], sub: subs }
    onUpdate({ ...config, aspects: copy })
  }

  return (
    <div className="card">
      <div className="flex-between mb-8">
        <h2>🩺 四燈號健診配置</h2>
        <button className="btn btn-primary btn-sm" onClick={onSave} disabled={saving}>
          {saving ? '儲存中...' : '儲存配置'}
        </button>
      </div>

      <h3 className="mb-8">面向權重 (加總須為 100)</h3>
      <div className="grid-4 mb-16">
        {Object.entries(aspectWeights).map(([key, val]) => (
          <div key={key}>
            <label>{aspects[key]?.label || key}</label>
            <input
              type="number" min={0} max={100} value={val as number}
              onChange={e => updateWeight(key, parseInt(e.target.value) || 0)}
            />
          </div>
        ))}
      </div>

      {Object.entries(aspects).map(([key, aspect]: [string, any]) => (
        <details key={key} style={{ marginBottom: 8 }}>
          <summary style={{ cursor: 'pointer', fontSize: 13, fontWeight: 600, padding: '8px 0' }}>
            {aspect.label} — 權重 {aspectWeights[key] || 25}%
          </summary>
          <table style={{ fontSize: 12 }}>
            <thead>
              <tr>
                <th style={{ width: '18%' }}>指標</th>
                <th style={{ width: '8%' }}>權重(%)</th>
                <th style={{ width: '27%' }}>計分方式</th>
                <th style={{ width: '27%' }}>計算公式</th>
                <th style={{ width: '20%' }}>結果</th>
              </tr>
            </thead>
            <tbody>
              {(aspect.sub || []).map((sub: any, i: number) => (
                <tr key={sub.key || sub.name}>
                  <td>{sub.name}</td>
                  <td>
                    <input
                      type="number" min={0} max={100} value={sub.weight || 0}
                      onChange={e => updateSubWeight(key, i, parseInt(e.target.value) || 0)}
                      style={{ width: 56, fontSize: 11, padding: '4px 6px' }}
                    />
                  </td>
                  <td>
                    <input
                      value={sub.scoring || ''}
                      onChange={e => updateSubScoring(key, i, e.target.value)}
                      style={{ fontSize: 11, padding: '4px 6px', width: '100%' }}
                    />
                  </td>
                  <td>
                    <input
                      value={sub.formula || ''}
                      onChange={e => updateSubFormula(key, i, e.target.value)}
                      style={{ fontSize: 11, padding: '4px 6px', width: '100%', fontFamily: 'monospace' }}
                    />
                  </td>
                  <td className="text-dim" style={{ fontSize: 11 }}>—</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      ))}
    </div>
  )
}
