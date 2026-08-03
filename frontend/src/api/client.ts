import type { Stock, StockDetail, MarketState, HealthScore, Rule, MultiTimeframeConsensus, Scorecard } from '../types'

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

export interface MonthlyRevenue {
  stock_id: string
  year_month: string
  revenue: number | null
  mom_change: number | null
  yoy_change: number | null
}

export interface QuarterlyFinancial {
  stock_id: string
  fiscal_quarter: string
  eps: number | null
  revenue: number | null
  gross_margin: number | null
  roe: number | null
  roa: number | null
}

export interface Dividend {
  stock_id: string
  year: number
  ex_date: string | null
  close_before_ex: number | null
  cash_dividend: number | null
  cash_pay_date: string | null
  cash_yield: number | null
  stock_dividend: number | null
}

export interface SectorRank {
  sector: string
  count: number
  avg_score: number
  members: { stock_id: string; stock_name: string; score: number }[]
}

export interface StockSectorRank {
  stock_id: string
  stock_name: string
  sector: string | null
  member_count: number
  percentiles: { eps: number | null; roe: number | null; roa: number | null }
  members: { stock_id: string; stock_name: string; eps: number | null; roe: number | null; roa: number | null; fiscal_quarter: string | null }[]
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
  monthlyRevenue: (id: string) => request<MonthlyRevenue[]>(`/stocks/${id}/monthly-revenue`),
  quarterlyFinancials: (id: string) => request<QuarterlyFinancial[]>(`/stocks/${id}/quarterly-financials`),
  dividends: (id: string) => request<Dividend[]>(`/stocks/${id}/dividends`),
  marginTrading: (id: string) => request<unknown[]>(`/stocks/${id}/margin-trading`),
  institutionalFlows: (id: string) => request<unknown[]>(`/stocks/${id}/institutional-flows`),
  sectorRanking: () => request<SectorRank[]>(`/sector-ranking`),
  stockSectorRanking: (id: string) => request<StockSectorRank>(`/stocks/${id}/sector-ranking`),
  scorecard: (id: string) => request<Scorecard>(`/signals/${id}/scorecard`),
  allScorecards: () => request<Scorecard[]>(`/signals/all/scorecard`),
  config: () => request<{ watch_stocks: string[] }>('/config'),
  updateConfig: (body: { watch_stocks?: string[] }) => request('/config', { method: 'PUT', body: JSON.stringify(body) }),
}
