export type ThesisStatus = 'open' | 'pending' | 'confirmed' | 'invalidated' | 'closed'
export type ReviewOutcome = 'correct' | 'wrong' | 'unclear'
export type DecisionQuality = 'good' | 'flawed' | 'unknown'
export type Stance = 'agree' | 'disagree'

export interface Thesis {
  id: string
  tickers: string[]
  author: string
  opened: string
  conviction: number
  claim: string
  falsifier: string
  reasoning: string | null
  evidence: string[]
  review_date: string
  status: ThesisStatus
  entry_price: number | null
  entry_date: string | null
  created_at: string
  // pre-commitment fields
  base_rate: string | null
  pre_mortem: string | null
  change_my_mind: string | null
  sizing_rationale: string | null
  why_now: string | null
  activate_at: string | null
  dissents?: Dissent[]
}

export interface ThesisIn {
  tickers: string[]
  author: string
  conviction: number
  claim: string
  falsifier: string
  review_date: string
  reasoning?: string | null
  evidence?: string[]
  entry_price?: number | null
  entry_date?: string | null
  base_rate?: string | null
  pre_mortem?: string | null
  change_my_mind?: string | null
  sizing_rationale?: string | null
  why_now?: string | null
  cooling_off_hours?: number | null
}

export interface ThesisPatch {
  status?: ThesisStatus
  reasoning?: string | null
  evidence?: string[]
  entry_price?: number | null
  entry_date?: string | null
}

export interface ReviewIn {
  outcome: ReviewOutcome
  decision_quality?: DecisionQuality
  note?: string | null
  reviewed_on?: string | null
}

export interface Dissent {
  id: string
  thesis_id: string
  author: string
  stance: Stance
  note: string | null
  created_at: string
}

export interface DissentIn {
  author: string
  stance: Stance
  note?: string | null
}

export interface TrendPoint {
  date: string
  brier: number
}

export interface CalibrationBucket {
  conviction: number
  total: number
  correct: number
  hit_rate: number
}

export interface Calibration {
  banner: string
  brier_score: number
  overconfident: boolean
  buckets: CalibrationBucket[]
  per_author: Record<string, number>
  process_score: number | null
  decision_counts: { good: number; flawed: number; unclear: number } | null
  trend: TrendPoint[]
}

export interface Prior {
  chunk: string
  source: string
  score: number
}

export interface PriorsIn {
  query: string
  ticker?: string | null
  k?: number
}

export interface DigestEntry {
  id: string
  tickers: string[]
  claim: string
  review_date: string
  days_until: number
}

export interface Digest {
  banner: string
  due: DigestEntry[]
  overdue: DigestEntry[]
}

export interface SenateTrade {
  senator: string
  transaction_type: string
  amount: string | null
  transaction_date: string | null
}

export interface MarketContext {
  price: number | null
  day_change_percent: number | null
  week_52_high: number | null
  week_52_low: number | null
  market_cap: number | null
  pe_ratio: number | null
  news_headlines: string[]
  news_urls: string[]
  company_name: string | null
  website: string | null
}

export interface TickerContext {
  banner: string
  ticker: string
  market?: MarketContext
  market_error?: string
  senate_trades?: SenateTrade[]
  senate_trades_error?: string
}

export interface PriceBar {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface PriceHistory {
  banner: string
  ticker: string
  period: string
  bars: PriceBar[]
}

export interface Candidate {
  ticker: string
  as_of_date: string
  discovered_at: string
  momentum_12_1: number | null
  vol_252d: number | null
  sharpe_12m: number | null
  above_200d_sma: boolean | null
  earnings_yield: number | null
  roe: number | null
  z_momentum: number | null
  z_low_vol: number | null
  z_sharpe: number | null
  z_value: number | null
  z_quality: number | null
  composite_score: number
  composite_rank: number
}

export interface CandidatesResponse {
  banner: string
  candidates: Candidate[]
  last_run: string | null
  count: number
}

export interface VolStock {
  ticker: string
  as_of_date: string
  computed_at: string
  lookback_days: number
  avg_dollar_range: number | null
  range_consistency: number | null
  avg_range_pct: number | null
  avg_close: number | null
  ari_special_score: number
  rank: number
}

export interface VolScreenResponse {
  banner: string
  stocks: VolStock[]
  last_run: string | null
  lookback_days: number | null
  count: number
}

export interface CandidateResponse {
  banner: string
  ticker: string
  candidate: Candidate | null
}

export interface CasePoint {
  factor: CortexFactor
  label: string
  z: number
  stat: string
  argument: string
  citation: string | null
  citation_text: string | null
}

export interface InvestmentCase {
  ticker: string
  composite_score: number
  composite_rank: number
  suggested_conviction: number
  trend_ok: boolean | null
  headline: string
  summary: string
  bull_points: CasePoint[]
  risk_points: CasePoint[]
  falsifier: string
}

export interface CaseResponse {
  banner: string
  ticker: string
  case: InvestmentCase | null
}

export type CortexFactor = 'momentum' | 'low_vol' | 'sharpe' | 'value' | 'quality'

export interface ResearchSnippet {
  wikilink: string
  tier: number | null
  text: string
}

export interface TickerResearch {
  banner: string
  ticker: string
  by_factor: Record<CortexFactor, ResearchSnippet[]>
  error: string | null
}

export interface CongressTrade {
  senator: string
  ticker: string
  transaction_type: string
  amount: string
  transaction_date: string | null
  disclosure_date: string | null
  asset_description: string
  report_url: string
}

export interface CongressResponse {
  banner: string
  ticker: string | null
  count: number
  trades: CongressTrade[]
}

export interface FundMove {
  manager: string
  ticker: string
  issuer: string
  action: string
  shares: number
  prev_shares: number
  value: number
  pct_change: number | null
  period: string | null
}

export interface FundsResponse {
  banner: string
  ticker: string | null
  count: number
  moves: FundMove[]
}

export interface RefreshStatus {
  banner: string
  status?: string
  running: boolean
  started_at: string | null
  finished_at: string | null
  steps: Record<string, string>
  error: string | null
}

export interface StockReasoning {
  trend: string
  rsi: string
  volume: string
  pe: string
  range: string
  market_cap: string
  cortex_summary: string
  momentum_factor: string
  low_vol_factor: string
  sharpe_factor: string
  value_factor: string
  quality_factor: string
}

export interface ReasoningResponse {
  banner: string
  ticker: string
  reasoning: StockReasoning
}

export const BANNER = 'Decision tool — not financial advice.'
