export interface Stock {
  id: string
  name: string
  close: number | null
  change_pct: number | null
  health_score: number | null
  health_light: string | null
  risk_score: number | null
  risk_level: string | null
}

export interface PricePoint {
  date: string
  close: number | null
  high: number | null
  low: number | null
  volume: number | null
  adj_close: number | null
  change_pct: number | null
}

export interface IndicatorPoint {
  date: string
  ma5: number | null
  ma20: number | null
  ma60: number | null
  bb_upper: number | null
  bb_middle: number | null
  bb_lower: number | null
  rsi14: number | null
  volume_ma5: number | null
  volume_ma20: number | null
}

export interface InstitutionalFlow {
  date: string
  foreign: number | null
  sity: number | null
  dealer: number | null
}

export interface FinancialQuarter {
  quarter: string
  eps: number | null
  revenue: number | null
  gross_margin: number | null
}

export interface HealthScore {
  stock_id: string
  fundamental_score: number
  fundamental_light: string
  institutional_score: number
  institutional_light: string
  technical_score: number
  technical_light: string
  valuation_score: number
  valuation_light: string
  total_score: number
  total_light: string
}

export interface RiskMetric {
  stock_id: string
  trade_date: string
  volatility_20d: number | null
  volatility_avg: number | null
  vol_ratio: number | null
  atr_14d: number | null
  atr_pct: number | null
  max_drawdown: number | null
  signal_conflict: number
  stop_loss_atr: number | null
  stop_loss_ma: number | null
  risk_level: string
  risk_score: number
}

export interface MarketState {
  state: string
  close: number
  ma60: number
  rsi: number
}

export interface StockDetail {
  stock_id: string
  name: string
  prices: PricePoint[]
  indicators: IndicatorPoint[]
  institutional: InstitutionalFlow[]
  features: Record<string, unknown> | null
  financials: FinancialQuarter[]
  health: HealthScore | null
  weekly_health: HealthScore | null
  risk: RiskMetric | null
  signals: Array<{ triggered_rules: string }>
  market_state: MarketState | null
  multi_timeframe: MultiTimeframeConsensus | null
}

export interface MultiTimeframeConsensus {
  stock_id: string
  trade_date: string
  daily_light: string | null
  weekly_light: string | null
  consensus: string
  consensus_label: string
  signal_type: string
  details: Record<string, unknown> | null
}

export interface Rule {
  _source: string
  id: string
  name: string
  type: string
  description: string
  failure_condition: string
  tags: string[]
  conditions: Record<string, unknown>
  weight?: number
}

export type Page = 'observation' | 'rules'
