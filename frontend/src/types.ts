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
  monthly_health: HealthScore | null
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

export interface ScorecardDetail {
  count: number
  ratio: string
  [key: string]: boolean | number | string
}

export interface Scorecard {
  stock_id: string
  trade_date: string | null
  bullish: ScorecardDetail
  bearish: ScorecardDetail
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

// T019: 訊號績效追蹤
export interface PerformanceAgg {
  triggers: number
  wins: number
  losses: number
  win_rate: number
  avg_return: number
  avg_win: number
  avg_loss: number
  profit_ratio: number
  max_dd: number
  max_consecutive_losses: number
  expectancy: number
}

export interface PerformanceRuleEntry {
  name: string
  type: string
  stats: PerformanceAgg
  by_state: Record<string, PerformanceAgg>
}

export interface PerformanceOverview {
  horizon: number
  days: number
  from_date: string
  to_date: string | null
  total_triggers: number
  win_rate: number
  avg_return: number
  avg_win: number
  avg_loss: number
  profit_ratio: number
  max_dd: number
  consecutive_losses: number
  expectancy: number
  by_state: Record<string, PerformanceAgg>
}

export interface PerformanceLog {
  id: number
  stock_id: string
  rule_id: string
  trigger_date: string
  market_state: string | null
  close_at_trigger: number | null
  after_1d_return: number | null
  after_3d_return: number | null
  after_5d_return: number | null
  after_10d_return: number | null
  inspection_date: string | null
}

// T010: 個股池訊號型別
export interface StockPoolRow {
  stock_id: string
  name: string
  sector: string | null
  total_score: number | null
  bullish_count: number | null
  bearish_count: number | null
  health_light: string | null
  technical_light: string | null
  consensus: string | null
  rs_5d: number | null
  rs_20d: number | null
  rs_60d: number | null
  rs_composite: number | null
  rs_label: string | null
  market_state: string | null
  market_consistent: boolean | null
  fundamental_light: string | null
  institutional_light: string | null
  valuation_light: string | null
}

export interface StockPoolCrossCompare {
  market_state: string | null
  consistent_count: number
  inconsistent_count: number
  no_data_count: number
  consistent_stocks: string[]
  inconsistent_stocks: string[]
  contrarian_stocks: string[]
  benchmark_id: string
  as_of: string
}

export interface StockPoolOverview {
  as_of: string
  market_state: string | null
  pool_size: number
  rows: StockPoolRow[]
  by_sector: Record<string, string[]>
  cross_compare: StockPoolCrossCompare
}

export interface StockPoolRelativeStrength {
  as_of: string
  benchmark_id: string
  rows: Array<{
    stock_id: string
    benchmark_id: string
    rs_5d: number | null
    rs_20d: number | null
    rs_60d: number | null
    label_5d: string | null
    label_20d: string | null
    label_60d: string | null
    composite: number | null
    composite_label: string | null
    as_of: string
  }>
}

export type Page = 'observation' | 'rules' | 'performance' | 'stock_pool'
