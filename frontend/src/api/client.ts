import type { Stock, StockDetail, MarketState, HealthScore, Rule, MultiTimeframeConsensus } from '../types'

const BASE = '/api'

async function request<T>(path: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  })
  const json = await res.json()
  if (!res.ok) throw new Error(json.detail || 'API error')
  return (json.data ?? json) as T
}

export const api = {
  listStocks: () => request<Stock[]>('/stocks'),
  stockDetail: (id: string) => request<StockDetail>(`/stocks/${id}/detail`),
  marketState: () => request<MarketState>('/market-state'),
  dashboard: () => request<{ stocks: Stock[]; market_state: MarketState | null; report: string }>('/dashboard'),
  healthScores: () => request<HealthScore[]>('/health'),
  weeklyHealth: () => request<HealthScore[]>('/weekly-health'),
  monthlyHealth: () => request<HealthScore[]>('/monthly-health'),
  multiTimeframe: () => request<MultiTimeframeConsensus[]>('/multi-timeframe'),
  healthCheckConfig: () => request<Record<string, any>>('/health-check-config'),
  updateHealthCheckConfig: (body: Record<string, any>) => request('/health-check-config', { method: 'PUT', body: JSON.stringify(body) }),
  rules: () => request<Rule[]>('/rules'),
  updateRules: (rules: Rule[]) => request('/rules', { method: 'PUT', body: JSON.stringify({ rules }) }),
  config: () => request<{ watch_stocks: string[] }>('/config'),
  updateConfig: (body: { watch_stocks?: string[] }) => request('/config', { method: 'PUT', body: JSON.stringify(body) }),
}
