import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowUpRight, Sparkles, TrendingDown, TrendingUp, X } from 'lucide-react'

import { AnalysisChart } from '@/components/charts/AnalysisChart'
import { TickerLogo } from '@/components/ui/TickerLogo'
import {
  useCandidate,
  useCase,
  useCongress,
  useFunds,
  useGenerateReasoning,
  useHistory,
  useTickerContext,
  useTickerResearch,
} from '@/lib/api'
import type { Candidate, CasePoint, CortexFactor, MarketContext, PriceBar, StockReasoning, Thesis, TickerResearch } from '@/lib/types'
import { cn, daysUntil, fmtDate, fmtPercent, fmtPrice, fmtSignedPercent } from '@/lib/utils'

// ── Technical computations ─────────────────────────────────────────────────────

function computeSMA(closes: number[], period: number): (number | null)[] {
  return closes.map((_, i) => {
    if (i < period - 1) return null
    return closes.slice(i - period + 1, i + 1).reduce((a, b) => a + b, 0) / period
  })
}

function computeRSI(closes: number[], period = 14): (number | null)[] {
  const result: (number | null)[] = new Array(closes.length).fill(null)
  if (closes.length < period + 1) return result

  let avgGain = 0
  let avgLoss = 0
  for (let i = 1; i <= period; i++) {
    const d = closes[i] - closes[i - 1]
    if (d > 0) avgGain += d
    else avgLoss += -d
  }
  avgGain /= period
  avgLoss /= period

  for (let i = period; i < closes.length; i++) {
    if (i > period) {
      const d = closes[i] - closes[i - 1]
      avgGain = (avgGain * (period - 1) + Math.max(0, d)) / period
      avgLoss = (avgLoss * (period - 1) + Math.max(0, -d)) / period
    }
    const rs = avgLoss === 0 ? Infinity : avgGain / avgLoss
    result[i] = 100 - 100 / (1 + rs)
  }
  return result
}

function computeReturn(bars: PriceBar[], daysAgo: number): number | null {
  if (bars.length < daysAgo + 1) return null
  const last = bars[bars.length - 1].close
  const ref = bars[Math.max(0, bars.length - 1 - daysAgo)].close
  return ((last - ref) / ref) * 100
}

function avgVolume(bars: PriceBar[], days: number): number {
  const slice = bars.slice(-days)
  if (slice.length === 0) return 0
  return slice.reduce((s, b) => s + b.volume, 0) / slice.length
}

// ── Plain-English interpretation helpers ───────────────────────────────────────

function getTrendContext(
  bars: PriceBar[],
  price: number,
): { label: string; tone: string; detail: string } {
  const closes = bars.map(b => b.close)
  const sma20 = computeSMA(closes, 20)
  const sma50 = computeSMA(closes, 50)
  const v20 = sma20[sma20.length - 1]
  const v50 = sma50[sma50.length - 1]

  if (!v20 || !v50) {
    return { label: 'INSUFFICIENT DATA', tone: 'text-muted', detail: 'Not enough price history to determine trend.' }
  }

  if (price > v20 && price > v50) {
    return {
      label: 'UPTREND',
      tone: 'text-up',
      detail: `Trading above both the 20-day (${fmtPrice(v20)}) and 50-day (${fmtPrice(v50)}) averages. Short- and long-term momentum are aligned — the trend is healthy.`,
    }
  }
  if (price < v20 && price < v50) {
    return {
      label: 'DOWNTREND',
      tone: 'text-down',
      detail: `Trading below both the 20-day (${fmtPrice(v20)}) and 50-day (${fmtPrice(v50)}) averages. Trend is negative on both timeframes — momentum is not supportive.`,
    }
  }
  if (price > v50 && price < v20) {
    return {
      label: 'PULLING BACK',
      tone: 'text-warn',
      detail: `Dipped under the 20-day average (${fmtPrice(v20)}) but still holds above the 50-day (${fmtPrice(v50)}). The primary trend is intact — this looks like a normal retracement.`,
    }
  }
  return {
    label: 'RECOVERING',
    tone: 'text-warn',
    detail: `Reclaimed the 20-day average (${fmtPrice(v20)}) but hasn't cleared the 50-day (${fmtPrice(v50)}) yet. Early evidence of recovery, not confirmed by the longer-term trend.`,
  }
}

function getRSIContext(rsi: number | null): {
  label: string
  tone: string
  explain: string
  emoji: string
} {
  if (rsi === null) return { label: '—', tone: 'text-muted', explain: '', emoji: '' }
  if (rsi >= 70) return {
    label: `${rsi.toFixed(0)} · Overbought`,
    tone: 'text-down',
    explain: 'The stock has run hard in a short window. Elevated RSI doesn\'t demand a sell, but short-term pullback risk is high.',
    emoji: '🔴',
  }
  if (rsi >= 60) return {
    label: `${rsi.toFixed(0)} · Strong`,
    tone: 'text-warn',
    explain: 'Momentum is positive without being stretched. Buyers are in control.',
    emoji: '🟡',
  }
  if (rsi >= 40) return {
    label: `${rsi.toFixed(0)} · Neutral`,
    tone: 'text-muted',
    explain: 'Buying and selling pressure are roughly balanced. No directional conviction from momentum.',
    emoji: '⚪',
  }
  if (rsi >= 30) return {
    label: `${rsi.toFixed(0)} · Weak`,
    tone: 'text-warn',
    explain: 'Selling has outpaced buying recently. Wait for momentum to stabilize before adding exposure.',
    emoji: '🟡',
  }
  return {
    label: `${rsi.toFixed(0)} · Oversold`,
    tone: 'text-up',
    explain: 'The stock has been sold aggressively in a short period. May set up a bounce — or reflect real deterioration. Check recent catalysts.',
    emoji: '🟢',
  }
}

function getPEContext(pe: number | null): string {
  if (pe == null || pe <= 0) return 'P/E not available — the company may not be profitable on a trailing basis.'
  if (pe > 60) return `At ${pe.toFixed(0)}×, the market is pricing in exceptional growth. Any miss on expectations tends to be punished severely.`
  if (pe > 35) return `At ${pe.toFixed(0)}×, you're paying a premium — the market expects sustained strong growth to justify it.`
  if (pe > 20) return `At ${pe.toFixed(0)}×, a modest premium to the S&P 500 average (~21×). Reasonable for a quality business with growth.`
  if (pe > 12) return `At ${pe.toFixed(0)}×, at or below the market average. The market expects modest growth — or is pricing in some risk.`
  return `At ${pe.toFixed(0)}×, cheap by market standards. Either a deep-value opportunity or a business under pressure. Investigate the discount.`
}

function getMarketCapLabel(cap: number): string {
  if (cap >= 1e12) return `$${(cap / 1e12).toFixed(1)}T — Mega-cap`
  if (cap >= 2e11) return `$${(cap / 1e9).toFixed(0)}B — Large-cap`
  if (cap >= 1e10) return `$${(cap / 1e9).toFixed(0)}B — Mid-large cap`
  if (cap >= 2e9)  return `$${(cap / 1e9).toFixed(1)}B — Mid-cap`
  return `$${(cap / 1e6).toFixed(0)}M — Small-cap`
}

function getMarketCapContext(cap: number | null): string {
  if (cap == null) return ''
  if (cap >= 1e12) return 'One of the largest companies in the world. Highly liquid, broadly owned by institutions globally.'
  if (cap >= 2e11) return 'A large, established company with deep institutional coverage and high liquidity.'
  if (cap >= 1e10) return 'Well-established with strong market presence and adequate liquidity for most portfolio sizes.'
  if (cap >= 2e9)  return 'Mid-cap — more growth runway than large-caps, but also more volatility.'
  return 'Small-cap — higher potential upside, but wider bid-ask spreads and less analyst coverage.'
}

function getRangeContext(price: number, low: number, high: number): string {
  const range = high - low
  if (range <= 0) return ''
  const pct = ((price - low) / range) * 100
  if (pct >= 80) return `Near the top of its 52-week range. The run has been strong — understand the catalyst before adding here.`
  if (pct >= 60) return `In the upper half of its 52-week range. Trending well, not at extremes.`
  if (pct >= 40) return `Mid-range over the past 52 weeks. Balanced price action with room in either direction.`
  if (pct >= 20) return `In the lower half of its 52-week range. Either a setup worth watching or persistent weakness — context matters.`
  return `Near its 52-week lows. Heavy selling has occurred. Know the reason before buying into it.`
}

function getVolumeContext(bars: PriceBar[]): string {
  if (bars.length < 30) return ''
  const recent = avgVolume(bars, 5)
  const baseline = avgVolume(bars, 30)
  if (baseline === 0) return ''
  const ratio = recent / baseline
  if (ratio > 2) return 'Volume is running more than double its normal level — a meaningful event is driving activity. Check recent news.'
  if (ratio > 1.4) return 'Volume is above its recent average — elevated interest from buyers or sellers.'
  if (ratio > 0.7) return 'Volume is in line with recent norms — no unusual activity.'
  return 'Volume is lighter than usual — limited conviction from market participants right now.'
}

// ── SVG chart helpers ──────────────────────────────────────────────────────────

function VolumeChart({ bars }: { bars: PriceBar[] }) {
  if (bars.length === 0) return null
  const maxVol = Math.max(...bars.map(b => b.volume))
  if (maxVol === 0) return null

  return (
    <svg
      viewBox={`0 0 ${bars.length} 100`}
      className="h-full w-full"
      preserveAspectRatio="none"
    >
      {bars.map((b, i) => {
        const h = (b.volume / maxVol) * 98
        const up = b.close >= b.open
        return (
          <rect
            key={i}
            x={i + 0.08}
            y={100 - h}
            width={0.84}
            height={h}
            fill={up ? 'rgba(74,222,128,0.42)' : 'rgba(248,113,113,0.42)'}
          />
        )
      })}
    </svg>
  )
}

function RSIChart({ bars }: { bars: PriceBar[] }) {
  const closes = bars.map(b => b.close)
  const rsiValues = computeRSI(closes)
  const n = rsiValues.length
  const currentRSI = rsiValues[n - 1]

  const validPairs = rsiValues
    .map((v, i) => (v !== null ? { i, v } : null))
    .filter((x): x is { i: number; v: number } => x !== null)

  if (validPairs.length < 5) return null

  const W = n
  const H = 100
  const scaleY = (v: number) => H - v

  const pathD = validPairs
    .map(({ i, v }, idx) => `${idx === 0 ? 'M' : 'L'}${i},${scaleY(v)}`)
    .join(' ')

  return (
    <div className="relative h-full">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-full w-full" preserveAspectRatio="none">
        <rect x={0} y={0} width={W} height={30} fill="rgba(248,113,113,0.05)" />
        <rect x={0} y={70} width={W} height={30} fill="rgba(74,222,128,0.05)" />
        <line x1={0} y1={30} x2={W} y2={30} stroke="rgba(248,113,113,0.3)" strokeWidth="0.8" strokeDasharray="3,3" />
        <line x1={0} y1={50} x2={W} y2={50} stroke="rgba(255,255,255,0.07)" strokeWidth="0.8" />
        <line x1={0} y1={70} x2={W} y2={70} stroke="rgba(74,222,128,0.3)" strokeWidth="0.8" strokeDasharray="3,3" />
        <path d={pathD} fill="none" stroke="#22d3ee" strokeWidth="1.2" />
        {currentRSI !== null && (
          <circle
            cx={validPairs[validPairs.length - 1].i}
            cy={scaleY(currentRSI)}
            r={2}
            fill="#22d3ee"
          />
        )}
      </svg>
      <div className="pointer-events-none absolute left-1 top-0.5 flex flex-col gap-4">
        <span className="num text-[8px] text-down/50">70</span>
      </div>
      <div className="pointer-events-none absolute bottom-0 left-1">
        <span className="num text-[8px] text-up/50">30</span>
      </div>
    </div>
  )
}

// ── Shared primitives ──────────────────────────────────────────────────────────

const STATUS_DOT: Record<string, string> = {
  open: 'bg-open', pending: 'bg-warn', confirmed: 'bg-up',
  invalidated: 'bg-down', closed: 'bg-muted',
}
const STATUS_TEXT: Record<string, string> = {
  open: 'text-open', pending: 'text-warn', confirmed: 'text-up',
  invalidated: 'text-down', closed: 'text-muted',
}

function ScorePill({ score }: { score: number }) {
  const cls =
    score >= 70 ? 'text-up bg-up/10 border-up/25'
    : score >= 50 ? 'text-warn bg-warn/10 border-warn/25'
    : 'text-muted bg-border/40 border-border'
  return (
    <span className={cn('num inline-flex items-center rounded-sm border px-1.5 py-0.5 text-[10px] font-bold', cls)}>
      {score}
    </span>
  )
}

function ConvBar({ value }: { value: number }) {
  return (
    <div className="flex items-center gap-1.5">
      <div className="flex gap-0.5">
        {Array.from({ length: 5 }, (_, i) => (
          <div
            key={i}
            className={cn(
              'h-1.5 w-2.5',
              i < value
                ? value >= 4 ? 'bg-up' : value === 3 ? 'bg-warn' : 'bg-open/60'
                : 'bg-border',
            )}
          />
        ))}
      </div>
      <span className="num text-[10px] text-faint">{value}/5</span>
    </div>
  )
}

function FactorBar({ label, score, max }: { label: string; score: number; max: number }) {
  return (
    <div className="space-y-0.5">
      <div className="flex items-center justify-between">
        <span className="label" style={{ fontSize: '9px' }}>{label}</span>
        <span className="num text-[9px] text-muted">{Math.round(score)}/{max}</span>
      </div>
      <div className="h-0.5 w-full bg-border">
        <div className="h-0.5 bg-cyan/60" style={{ width: `${(score / max) * 100}%` }} />
      </div>
    </div>
  )
}

function RangeBar({ low, high, current, entry }: {
  low: number; high: number; current: number; entry?: number | null
}) {
  const range = high - low
  if (range <= 0) return null
  const pct = Math.max(0, Math.min(100, ((current - low) / range) * 100))
  const entryPct = entry != null ? Math.max(0, Math.min(100, ((entry - low) / range) * 100)) : null
  return (
    <div className="relative h-1.5 w-full bg-border">
      <div className="absolute inset-y-0 left-0 bg-cyan/35" style={{ width: `${pct}%` }} />
      {entryPct != null && (
        <div
          className="absolute top-1/2 h-3.5 w-px -translate-y-1/2 bg-warn"
          style={{ left: `${entryPct}%` }}
        />
      )}
      <div
        className="absolute top-1/2 h-4 w-1.5 -translate-x-1/2 -translate-y-1/2 bg-cyan"
        style={{ left: `${pct}%` }}
      />
    </div>
  )
}

function ReturnBadge({ value }: { value: number | null }) {
  if (value == null) return <span className="num text-[12px] text-faint">—</span>
  const up = value >= 0
  return (
    <span className={cn('num text-[13px] font-semibold', up ? 'text-up' : 'text-down')}>
      {up ? '+' : ''}{value.toFixed(1)}%
    </span>
  )
}

// ── Signal scoring (same as Dashboard) ────────────────────────────────────────

function computeFactors(thesis: Thesis, market: MarketContext | undefined) {
  const conviction = (thesis.conviction / 5) * 40

  let valueZone = 0
  if (market?.price != null && market.week_52_high != null && market.week_52_low != null) {
    const range = market.week_52_high - market.week_52_low
    if (range > 0) {
      const pos = (market.price - market.week_52_low) / range
      valueZone = pos < 0.33 ? 25 : pos < 0.5 ? 15 : pos < 0.75 ? 5 : 0
    }
  }

  let momentum = 0
  if (market?.day_change_percent != null) {
    const d = market.day_change_percent
    momentum = d > 2 ? 20 : d > 0 ? 10 : d > -2 ? 5 : 0
  }

  const research =
    (thesis.why_now ? 5 : 0) + (thesis.base_rate ? 5 : 0) + (thesis.pre_mortem ? 5 : 0)

  return {
    conviction,
    valueZone,
    momentum,
    research,
    total: Math.min(100, Math.round(conviction + valueZone + momentum + research)),
  }
}

// ── Tab panels ─────────────────────────────────────────────────────────────────

const PERIODS = ['1mo', '3mo', '6mo', '1y'] as const
type Period = (typeof PERIODS)[number]
const PERIOD_LABELS: Record<Period, string> = { '1mo': '1M', '3mo': '3M', '6mo': '6M', '1y': '1Y' }

type Tab = 'overview' | 'case' | 'cortex' | 'charts' | 'thesis'

function OverviewTab({
  thesis,
  bars,
  market,
  ctx,
  reasoning,
}: {
  thesis?: Thesis
  bars: PriceBar[]
  market: MarketContext | undefined
  ctx: ReturnType<typeof useTickerContext>['data']
  reasoning: StockReasoning | null
}) {
  const price = market?.price ?? null
  const ret1m  = computeReturn(bars, 21)
  const ret3m  = computeReturn(bars, 63)
  const ret6m  = computeReturn(bars, 126)
  const trend  = price != null && bars.length >= 50 ? getTrendContext(bars, price) : null
  const closes = bars.map(b => b.close)
  const rsiVals = computeRSI(closes)
  const currentRSI = rsiVals[rsiVals.length - 1] ?? null
  const rsiCtx = getRSIContext(currentRSI)
  const volCtx = getVolumeContext(bars)

  return (
    <div className="grid grid-cols-[1fr_340px] gap-0 overflow-y-auto">
      {/* Left column */}
      <div className="overflow-y-auto border-r border-border p-6 space-y-4">

        {/* Trend snapshot */}
        {trend && (
          <div className="space-y-2 rounded-sm border border-border-bright bg-surface-raised p-4">
            <span className="label block">TREND SNAPSHOT</span>
            <div className="flex items-center gap-2">
              <span className={cn('num text-xs font-bold tracking-widest', trend.tone)}>
                {trend.label}
              </span>
            </div>
            <p className="font-sans text-[12px] leading-relaxed text-muted border-l-2 border-cyan/30 pl-3">
              {reasoning?.trend ?? trend.detail}
            </p>
          </div>
        )}

        {/* Momentum */}
        <div className="space-y-2 rounded-sm border border-border-bright bg-surface-raised p-4">
          <span className="label block">MOMENTUM (RSI)</span>
          <div className="flex items-center gap-2">
            <span className="text-sm">{rsiCtx.emoji}</span>
            <span className={cn('num text-xs font-bold tracking-widest', rsiCtx.tone)}>
              {rsiCtx.label}
            </span>
          </div>
          {(reasoning?.rsi || rsiCtx.explain) && (
            <p className="font-sans text-[12px] leading-relaxed text-muted border-l-2 border-cyan/30 pl-3">
              {reasoning?.rsi ?? rsiCtx.explain}
            </p>
          )}
          <p className="font-sans text-[11px] text-muted">
            RSI quantifies buying and selling momentum on a 0–100 scale. Above 70 signals the move is stretched; below 30 signals aggressive selling.
          </p>
        </div>

        {/* Volume context */}
        {volCtx && (
          <div className="space-y-2 rounded-sm border border-border-bright bg-surface-raised p-4">
            <span className="label block">TRADING ACTIVITY</span>
            <p className="font-sans text-[12px] leading-relaxed text-muted border-l-2 border-cyan/30 pl-3">
              {reasoning?.volume ?? volCtx}
            </p>
            <p className="font-sans text-[11px] text-muted">
              Volume reflects conviction. A price move on elevated volume is more reliable than one on thin activity.
            </p>
          </div>
        )}

        {/* News */}
        {market?.news_headlines && market.news_headlines.length > 0 && (
          <div className="space-y-2 rounded-sm border border-border-bright bg-surface-raised p-4">
            <span className="label block">RECENT NEWS</span>
            <div className="space-y-2">
              {market.news_headlines.slice(0, 5).map((h, i) => {
                const url = market.news_urls?.[i]
                return url ? (
                  <a
                    key={i}
                    href={url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex gap-3 border-l-2 border-cyan/30 pl-3 group/news"
                  >
                    <p className="font-sans text-[12px] leading-snug text-muted group-hover/news:text-ink transition-colors">
                      {h} <span className="text-faint">↗</span>
                    </p>
                  </a>
                ) : (
                  <div key={i} className="flex gap-3 border-l-2 border-border pl-3">
                    <p className="font-sans text-[12px] leading-snug text-muted">{h}</p>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* Senate trades */}
        {ctx?.senate_trades && ctx.senate_trades.length > 0 && (
          <div className="space-y-2 rounded-sm border border-border-bright bg-surface-raised p-4">
            <span className="label block">SENATE ACTIVITY</span>
            <p className="font-sans text-[11px] text-muted">
              Members of Congress are required to disclose stock trades. Significant insider buying can be a useful data point.
            </p>
            <div className="space-y-1.5">
              {ctx.senate_trades.slice(0, 4).map((t, i) => (
                <div key={i} className="flex items-center justify-between border-b border-border-dim pb-1.5">
                  <span className="font-sans text-[12px] text-ink">{t.senator}</span>
                  <div className="flex items-center gap-2">
                    <span className={cn(
                      'num text-[10px] font-semibold',
                      t.transaction_type.toLowerCase().includes('purchase') ? 'text-up' : 'text-down',
                    )}>
                      {t.transaction_type}
                    </span>
                    {t.amount && <span className="num text-[10px] text-muted">{t.amount}</span>}
                    {t.transaction_date && (
                      <span className="num text-[9px] text-faint">{t.transaction_date}</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Right column */}
      <div className="overflow-y-auto p-6 space-y-4">

        {/* Returns */}
        <div className="space-y-3 rounded-sm border border-border-bright bg-surface-raised p-4">
          <span className="label block">HOW HAS IT PERFORMED?</span>
          <p className="font-sans text-[11px] text-muted">
            Total price return over each lookback window. Compares where the stock is now vs. where it was.
          </p>
          <div className="space-y-2">
            {[
              { label: 'Last month', value: ret1m },
              { label: 'Last 3 months', value: ret3m },
              { label: 'Last 6 months', value: ret6m },
            ].map(({ label, value }) => (
              <div key={label} className="flex items-center justify-between border-b border-border-dim pb-2">
                <span className="font-sans text-[12px] text-muted">{label}</span>
                <ReturnBadge value={value} />
              </div>
            ))}
          </div>
        </div>

        {/* 52W Range */}
        {market?.week_52_low != null && market.week_52_high != null && price != null && (
          <div className="space-y-3 rounded-sm border border-border-bright bg-surface-raised p-4">
            <span className="label block">12-MONTH PRICE RANGE</span>
            <div className="space-y-2">
              <RangeBar
                low={market.week_52_low}
                high={market.week_52_high}
                current={price}
                entry={thesis?.entry_price}
              />
              <div className="flex items-center justify-between">
                <div>
                  <span className="num block text-[10px] text-muted">Year low</span>
                  <span className="num text-[11px] text-ink">{fmtPrice(market.week_52_low)}</span>
                </div>
                {thesis?.entry_price != null && (
                  <div className="text-center">
                    <span className="num block text-[10px] text-warn">Your entry</span>
                    <span className="num text-[11px] text-warn">{fmtPrice(thesis.entry_price)}</span>
                  </div>
                )}
                <div className="text-right">
                  <span className="num block text-[10px] text-muted">Year high</span>
                  <span className="num text-[11px] text-ink">{fmtPrice(market.week_52_high)}</span>
                </div>
              </div>
              <p className="font-sans text-[11px] leading-relaxed text-muted">
                {reasoning?.range ?? getRangeContext(price, market.week_52_low, market.week_52_high)}
              </p>
            </div>
          </div>
        )}

        {/* P/E */}
        {market?.pe_ratio != null && (
          <div className="space-y-2 rounded-sm border border-border-bright bg-surface-raised p-4">
            <span className="label block">PRICE VS EARNINGS (P/E)</span>
            <div className="flex items-baseline gap-2">
              <span className="num text-2xl font-semibold text-ink">
                {market.pe_ratio.toFixed(1)}×
              </span>
              <span className="num text-[10px] text-muted">vs S&P avg ~21×</span>
            </div>
            <p className="font-sans text-[12px] leading-relaxed text-muted">
              {reasoning?.pe ?? getPEContext(market.pe_ratio)}
            </p>
          </div>
        )}

        {/* Market Cap */}
        {market?.market_cap != null && (
          <div className="space-y-2 rounded-sm border border-border-bright bg-surface-raised p-4">
            <span className="label block">COMPANY SIZE</span>
            <div className="num text-base font-semibold text-ink">
              {getMarketCapLabel(market.market_cap)}
            </div>
            <p className="font-sans text-[12px] leading-relaxed text-muted">
              {reasoning?.market_cap ?? getMarketCapContext(market.market_cap)}
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

function ChartsTab({
  thesis,
  ticker,
}: {
  thesis?: Thesis
  ticker: string
}) {
  const [period, setPeriod] = useState<Period>('6mo')
  const { data: bars = [] } = useHistory(ticker, period)
  const { data: barsYear = [] } = useHistory(ticker, '1y')

  const closes = barsYear.map(b => b.close)
  const sma20 = computeSMA(closes, 20)
  const sma50 = computeSMA(closes, 50)
  const v20 = sma20[sma20.length - 1]
  const v50 = sma50[sma50.length - 1]
  const currentPrice = barsYear.length > 0 ? barsYear[barsYear.length - 1].close : null

  const rsiVals = computeRSI(closes)
  const currentRSI = rsiVals[rsiVals.length - 1] ?? null

  return (
    <div className="overflow-y-auto p-6 space-y-8">

      {/* Price chart + SMA */}
      <div className="space-y-3 rounded-sm border border-border-bright bg-surface-raised p-4">
        <div className="flex items-center justify-between">
          <div>
            <span className="label block">PRICE CHART</span>
            <p className="font-sans text-[11px] text-muted mt-0.5">
              Yellow line = 20-day average &nbsp;·&nbsp; Purple dashed = 50-day average
            </p>
          </div>
          <div className="flex items-center gap-px">
            {PERIODS.map(p => (
              <button
                key={p}
                onClick={() => setPeriod(p)}
                className={cn(
                  'num px-3 py-1 text-[10px] font-semibold tracking-widest transition-colors',
                  period === p ? 'border-b border-cyan text-cyan' : 'text-muted hover:text-ink',
                )}
              >
                {PERIOD_LABELS[p]}
              </button>
            ))}
          </div>
        </div>

        <div className="border border-border bg-bg">
          <AnalysisChart bars={bars} entryPrice={thesis?.entry_price} height={220} showSMA />
        </div>

        <div className="grid grid-cols-3 gap-3">
          <div className="border border-border-bright bg-bg p-3 space-y-0.5">
            <span className="label block text-[10px] text-muted">20-DAY AVERAGE</span>
            <span className="num text-[13px] font-semibold text-ink">{v20 ? fmtPrice(v20) : '—'}</span>
            {v20 != null && currentPrice != null && (
              <span className={cn('num block text-[10px]', currentPrice > v20 ? 'text-up' : 'text-down')}>
                {currentPrice > v20 ? '↑ Price above — bullish' : '↓ Price below — bearish'}
              </span>
            )}
          </div>
          <div className="border border-border-bright bg-bg p-3 space-y-0.5">
            <span className="label block text-[10px] text-muted">50-DAY AVERAGE</span>
            <span className="num text-[13px] font-semibold text-ink">{v50 ? fmtPrice(v50) : '—'}</span>
            {v50 != null && currentPrice != null && (
              <span className={cn('num block text-[10px]', currentPrice > v50 ? 'text-up' : 'text-down')}>
                {currentPrice > v50 ? '↑ Price above — bullish' : '↓ Price below — bearish'}
              </span>
            )}
          </div>
          <div className="border border-border-bright bg-bg p-3 space-y-0.5">
            <span className="label block text-[10px] text-muted">WHAT THIS MEANS</span>
            <p className="font-sans text-[10px] leading-snug text-muted">
              Price above its averages means buyers are consistently willing to pay up — a sign of sustained demand.
            </p>
          </div>
        </div>
      </div>

      {/* Volume */}
      <div className="space-y-3 rounded-sm border border-border-bright bg-surface-raised p-4">
        <div>
          <span className="label block">TRADING VOLUME</span>
          <p className="font-sans text-[11px] text-muted mt-0.5">
            How many shares traded each day. Green = price went up that day. Red = price fell.
          </p>
        </div>
        <div className="h-16 border border-border bg-bg p-1">
          <VolumeChart bars={bars} />
        </div>
        <p className="font-sans text-[11px] text-muted">
          Volume spikes typically accompany earnings, news events, or large institutional flows. A price move on high volume carries more conviction than one on thin activity.
        </p>
      </div>

      {/* RSI */}
      <div className="space-y-3 rounded-sm border border-border-bright bg-surface-raised p-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <span className="label block">MOMENTUM INDICATOR (RSI)</span>
            <p className="font-sans text-[11px] text-muted mt-0.5">
              Measures momentum on a 0–100 scale. Above 70 signals a stretched move; below 30 signals a sharp sell-off.
            </p>
          </div>
          {currentRSI != null && (
            <div className="shrink-0 text-right">
              <span className="label block text-[10px] text-muted">CURRENT RSI</span>
              <span className={cn('num text-lg font-bold', getRSIContext(currentRSI).tone)}>
                {currentRSI.toFixed(0)}
              </span>
            </div>
          )}
        </div>
        <div className="h-20 border border-border bg-bg p-1">
          <RSIChart bars={barsYear} />
        </div>
        <div className="grid grid-cols-3 gap-2 text-center">
          <div className="border border-down/20 bg-down/5 p-2">
            <span className="label block text-[10px]" style={{ color: 'var(--color-down)' }}>ABOVE 70</span>
            <span className="font-sans text-[10px] text-muted">Stretched — elevated pullback risk</span>
          </div>
          <div className="border border-border-bright bg-bg p-2">
            <span className="label block text-[10px] text-muted">40–60</span>
            <span className="font-sans text-[10px] text-muted">Neutral — balanced momentum</span>
          </div>
          <div className="border border-up/20 bg-up/5 p-2">
            <span className="label block text-[10px]" style={{ color: 'var(--color-up)' }}>BELOW 30</span>
            <span className="font-sans text-[10px] text-muted">Aggressively sold — potential setup, verify catalyst</span>
          </div>
        </div>
      </div>
    </div>
  )
}

function ThesisTab({
  thesis,
  market,
  factors,
  candidate,
}: {
  thesis: Thesis
  market: MarketContext | undefined
  factors: ReturnType<typeof computeFactors>
  candidate: Candidate | null | undefined
}) {
  const days = daysUntil(thesis.review_date)
  const overdue = days < 0
  const price = market?.price ?? null
  const pnl =
    thesis.entry_price != null && price != null
      ? ((price - thesis.entry_price) / thesis.entry_price) * 100
      : null

  return (
    <div className="grid grid-cols-2 overflow-y-auto">
      {/* Left: thesis content */}
      <div className="overflow-y-auto border-r border-border p-6 space-y-5">

        <div className="space-y-1.5">
          <span className="label block">THESIS (THE BET)</span>
          <p className="font-sans text-[13px] leading-relaxed text-ink border-l-2 border-cyan/50 pl-3">
            {thesis.claim}
          </p>
        </div>

        <div className="space-y-1.5">
          <span className="label block">THIS THESIS IS WRONG IF...</span>
          <p className="font-sans text-[12px] leading-relaxed text-muted border-l-2 border-down/40 pl-3">
            {thesis.falsifier}
          </p>
          <p className="font-sans text-[11px] text-muted">
            Knowing your exit condition before you enter is one of the most important risk disciplines in investing.
          </p>
        </div>

        {thesis.why_now && (
          <div className="space-y-1.5">
            <span className="label block">WHY NOW (NOT LATER)?</span>
            <p className="font-sans text-[12px] leading-relaxed text-muted">{thesis.why_now}</p>
          </div>
        )}

        {thesis.base_rate && (
          <div className="space-y-1.5">
            <span className="label block">BASE RATE (HOW OFTEN DOES THIS HAPPEN?)</span>
            <p className="font-sans text-[12px] leading-relaxed text-muted">{thesis.base_rate}</p>
            <p className="font-sans text-[11px] text-muted">
              Base rates anchor your forecast to historical reality rather than the optimism of your current thesis.
            </p>
          </div>
        )}

        {thesis.pre_mortem && (
          <div className="space-y-1.5">
            <span className="label block">PRE-MORTEM (IF THIS FAILS, WHY?)</span>
            <p className="font-sans text-[12px] leading-relaxed text-muted">{thesis.pre_mortem}</p>
          </div>
        )}

        {thesis.reasoning && (
          <div className="space-y-1.5">
            <span className="label block">REASONING</span>
            <p className="font-sans text-[12px] leading-relaxed text-muted">{thesis.reasoning}</p>
          </div>
        )}
      </div>

      {/* Right: meta + signal */}
      <div className="overflow-y-auto p-6 space-y-5">

        {/* Position info */}
        <div className="space-y-2">
          <span className="label block">POSITION INFO</span>
          <div className="space-y-2">
            <div className="flex items-center justify-between border-b border-border-dim pb-1.5">
              <span className="font-sans text-[12px] text-muted">Status</span>
              <span className={cn('num text-[11px] font-bold tracking-widest', STATUS_TEXT[thesis.status] ?? 'text-muted')}>
                {thesis.status.toUpperCase()}
              </span>
            </div>
            <div className="flex items-center justify-between border-b border-border-dim pb-1.5">
              <span className="font-sans text-[12px] text-muted">Author</span>
              <span className="num text-[11px] text-ink">{thesis.author.toUpperCase()}</span>
            </div>
            <div className="flex items-center justify-between border-b border-border-dim pb-1.5">
              <span className="font-sans text-[12px] text-muted">Conviction</span>
              <ConvBar value={thesis.conviction} />
            </div>
            {thesis.entry_price != null && (
              <div className="flex items-center justify-between border-b border-border-dim pb-1.5">
                <span className="font-sans text-[12px] text-muted">Entry price</span>
                <div className="text-right">
                  <span className="num text-[12px] text-ink">{fmtPrice(thesis.entry_price)}</span>
                  {pnl != null && (
                    <span className={cn('num block text-[10px]', pnl >= 0 ? 'text-up' : 'text-down')}>
                      {pnl >= 0 ? '+' : ''}{pnl.toFixed(2)}% today
                    </span>
                  )}
                </div>
              </div>
            )}
            <div className="flex items-center justify-between border-b border-border-dim pb-1.5">
              <span className="font-sans text-[12px] text-muted">Review date</span>
              <div className="text-right">
                <span className="num block text-[12px] text-ink">{fmtDate(thesis.review_date)}</span>
                <span className={cn('num text-[10px]', overdue ? 'text-down' : days <= 7 ? 'text-warn' : 'text-faint')}>
                  {overdue ? `${Math.abs(days)}d overdue` : days === 0 ? 'Today' : `${days}d remaining`}
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Signal score */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="label block">COMPOSITE SIGNAL SCORE</span>
            <ScorePill score={factors.total} />
          </div>
          <p className="font-sans text-[11px] text-muted">
            A 0–100 score built from four factors. Useful for comparing ideas — not a buy or sell signal.
          </p>
          <div className="space-y-2.5">
            <div>
              <FactorBar label="CONVICTION (how strongly you believe it)" score={factors.conviction} max={40} />
            </div>
            <div>
              <FactorBar label="VALUE ZONE (where it sits in its yearly range)" score={factors.valueZone} max={25} />
            </div>
            <div>
              <FactorBar label="MOMENTUM (how it's trading today)" score={factors.momentum} max={20} />
            </div>
            <div>
              <FactorBar label="RESEARCH QUALITY (pre-mortem, base rate, why now)" score={factors.research} max={15} />
            </div>
          </div>
          <p className="font-sans text-[11px] text-muted">
            Add a Why Now, Base Rate, and Pre-Mortem to your thesis to raise the Research Quality component.
          </p>
        </div>

        {/* CORTEX verdict — systematic cross-check */}
        <div className="space-y-2 border border-border bg-bg-row p-3">
          <div className="flex items-center justify-between">
            <span className="label block">CORTEX VERDICT</span>
            {candidate ? (
              <span className={cn(
                'num text-[13px] font-bold',
                candidate.composite_score >= 0.5 ? 'text-up'
                : candidate.composite_score >= 0 ? 'text-warn' : 'text-down',
              )}>
                {candidate.composite_score >= 0 ? '+' : ''}{candidate.composite_score.toFixed(2)}σ · #{candidate.composite_rank}
              </span>
            ) : (
              <span className="num text-[11px] text-faint">NOT SCORED</span>
            )}
          </div>
          {candidate ? (
            <p className="font-sans text-[11px] leading-relaxed text-muted">
              The 6-factor model ranks this <span className="text-ink">#{candidate.composite_rank}</span> in
              the discovery universe. Your thesis is the human judgment; CORTEX is the systematic
              cross-check. Alignment between the two strengthens conviction. Divergence deserves
              investigation. See the <span className="text-cyan">CORTEX</span> tab for the full breakdown.
            </p>
          ) : (
            <p className="font-sans text-[11px] leading-relaxed text-muted">
              This ticker isn't in the current discovery run — likely fell below the 200-day trend gate or
              the pre-filter. Run <code className="font-mono text-cyan">wst discover</code> to re-score the universe.
            </p>
          )}
        </div>

        {/* Dissents */}
        {thesis.dissents && thesis.dissents.length > 0 && (
          <div className="space-y-2">
            <span className="label block">DISSENTING VIEWS</span>
            {thesis.dissents.map(d => (
              <div key={d.id} className="border border-border p-3 space-y-1">
                <div className="flex items-center justify-between">
                  <span className="num text-[11px] text-ink">{d.author}</span>
                  <span className={cn('num text-[10px] font-bold', d.stance === 'disagree' ? 'text-down' : 'text-up')}>
                    {d.stance.toUpperCase()}
                  </span>
                </div>
                {d.note && <p className="font-sans text-[11px] text-muted">{d.note}</p>}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ── CORTEX factor tab ──────────────────────────────────────────────────────────

const CORTEX_FACTORS: {
  key: CortexFactor
  label: string
  source: string
  blurb: string
  raw: (c: Candidate) => string
  z: (c: Candidate) => number | null
}[] = [
  {
    key: 'momentum',
    label: 'MOMENTUM (12-1)',
    source: 'Jegadeesh-Titman 1993 · Gray Quantitative Momentum',
    blurb: '12-month trailing return, excluding the most recent month to avoid short-term reversal bias. Persistent winners tend to continue outperforming over 3–12 month windows.',
    raw: c => `${fmtPercent(c.momentum_12_1)} trailing`,
    z: c => c.z_momentum,
  },
  {
    key: 'low_vol',
    label: 'LOW VOLATILITY',
    source: 'Baker 2011 low-vol anomaly · Frazzini-Pedersen BAB',
    blurb: 'Annualized realized volatility, inverted. Low-volatility stocks have historically outperformed on a risk-adjusted basis — a well-documented anomaly that contradicts standard asset pricing theory.',
    raw: c => `${fmtPercent(c.vol_252d)} annual vol`,
    z: c => c.z_low_vol,
  },
  {
    key: 'sharpe',
    label: 'RISK-ADJUSTED RETURN',
    source: 'Sharpe ratio · Moskowitz 2012 time-series momentum',
    blurb: '12-month return per unit of volatility. Favors smooth, sustained trends over erratic moves that happen to net the same price change.',
    raw: c => (c.sharpe_12m != null ? `${c.sharpe_12m.toFixed(2)} ratio` : '—'),
    z: c => c.z_sharpe,
  },
  {
    key: 'value',
    label: 'VALUE (EARNINGS YIELD)',
    source: 'Gray-Carlisle Quantitative Value · Fama-French 1992',
    blurb: 'Earnings yield (inverse P/E). Higher yield means less paid per dollar of profit — the foundational value signal with decades of documented return premium.',
    raw: c => `${fmtPercent(c.earnings_yield)} earnings yield`,
    z: c => c.z_value,
  },
  {
    key: 'quality',
    label: 'QUALITY (ROE)',
    source: 'Novy-Marx 2013 · Piotroski F-Score · Asness QMJ',
    blurb: 'Return on equity. High-ROE businesses compound capital efficiently and tend to hold up better in drawdowns relative to lower-quality peers.',
    raw: c => `${fmtPercent(c.roe)} ROE`,
    z: c => c.z_quality,
  },
]

function zInterpret(z: number | null): { label: string; tone: string } {
  if (z == null) return { label: 'NO DATA', tone: 'text-muted' }
  if (z >= 1.0) return { label: 'TOP-TIER', tone: 'text-up' }
  if (z >= 0.4) return { label: 'STRONG', tone: 'text-up' }
  if (z >= -0.4) return { label: 'AVERAGE', tone: 'text-muted' }
  if (z >= -1.0) return { label: 'WEAK', tone: 'text-warn' }
  return { label: 'POOR', tone: 'text-down' }
}

function ZBar({ z }: { z: number | null }) {
  if (z == null) return <div className="h-2 w-full bg-border" />
  const clamped = Math.max(-3, Math.min(3, z))
  const pct = ((clamped + 3) / 6) * 100
  const left = Math.min(50, pct)
  const width = Math.abs(pct - 50)
  const fill = z >= 0.4 ? 'bg-up' : z >= -0.4 ? 'bg-muted' : z >= -1.0 ? 'bg-warn' : 'bg-down'
  return (
    <div className="relative h-2 w-full bg-border/60">
      <div className="absolute inset-y-0 left-1/2 w-px bg-faint/60" />
      <div className={cn('absolute inset-y-0', fill)} style={{ left: `${left}%`, width: `${width}%` }} />
    </div>
  )
}

function ResearchSnippet({ research, factor }: { research: TickerResearch | undefined; factor: CortexFactor }) {
  const snippets = research?.by_factor?.[factor] ?? []
  if (snippets.length === 0) return null
  const top = snippets[0]
  // Strip YAML frontmatter noise from the chunk preview
  const clean = top.text.replace(/^---[\s\S]*?---/, '').replace(/\s+/g, ' ').trim()
  const preview = clean.slice(0, 220)
  const name = top.wikilink.replace(/^\[\[|\]\]$/g, '').split('/').pop() ?? top.wikilink
  return (
    <div className="mt-2 border-l-2 border-cyan/30 bg-cyan/[0.03] py-1.5 pl-3 pr-2">
      <div className="mb-0.5 flex items-center gap-1.5">
        <span className="num text-[9px] tracking-widest text-cyan/70">FROM VAULT</span>
        <span className="font-sans text-[10px] text-faint">{name}</span>
      </div>
      <p className="font-sans text-[11px] leading-snug text-muted">{preview}…</p>
    </div>
  )
}

function CortexTab({
  candidate,
  research,
  loading,
  reasoning,
}: {
  candidate: Candidate | null | undefined
  research: TickerResearch | undefined
  loading: boolean
  reasoning: StockReasoning | null
}) {
  if (loading) {
    return (
      <div className="flex items-center justify-center p-12">
        <span className="num text-sm text-muted">LOADING CORTEX…</span>
      </div>
    )
  }
  if (!candidate) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 p-12 text-center">
        <span className="num text-sm text-muted">NOT IN DISCOVERY SET</span>
        <p className="max-w-md font-sans text-[12px] leading-relaxed text-muted">
          This ticker isn't in the latest CORTEX run — it either fell below the 200-day
          trend gate or didn't clear the pre-filter. Run{' '}
          <code className="font-mono text-cyan">wst discover</code> to re-score the universe.
        </p>
      </div>
    )
  }

  const comp = candidate.composite_score
  const compTone = comp >= 0.5 ? 'text-up' : comp >= 0 ? 'text-warn' : 'text-down'

  return (
    <div className="overflow-y-auto p-6 space-y-6">
      {/* Composite header */}
      <div className="flex items-stretch gap-4">
        <div className="flex flex-col justify-center border border-border bg-bg-row px-5 py-3">
          <span className="label block text-faint" style={{ fontSize: '9px' }}>COMPOSITE</span>
          <span className={cn('num text-3xl font-bold leading-none', compTone)}>
            {comp >= 0 ? '+' : ''}{comp.toFixed(2)}
            <span className="text-base">z</span>
          </span>
          <span className="num mt-1 text-[10px] text-faint">RANK #{candidate.composite_rank} of discovered</span>
        </div>
        <div className="flex flex-1 flex-col justify-center gap-1.5">
          <p className="font-sans text-[12px] leading-relaxed text-muted">
            {reasoning?.cortex_summary ?? (
              <>CORTEX ranks every S&amp;P 500 name across six evidence-backed factors, z-scores each
              cross-sectionally, then equal-weights them into a composite. The score reflects where
              this name stands relative to the full universe — not an absolute grade.</>
            )}
          </p>
          <div className="flex items-center gap-2">
            <span className="num text-[10px] tracking-widest text-faint">200-DAY TREND GATE</span>
            <span className={cn(
              'num text-[10px] font-bold',
              candidate.above_200d_sma ? 'text-up' : 'text-down',
            )}>
              {candidate.above_200d_sma ? '✓ ABOVE — eligible' : '✕ BELOW — would be excluded'}
            </span>
          </div>
        </div>
      </div>

      {/* Factor breakdown */}
      <div className="space-y-4">
        <span className="label block">FACTOR BREAKDOWN</span>
        {CORTEX_FACTORS.map(f => {
          const z = f.z(candidate)
          const interp = zInterpret(z)
          const reasoningKey = `${f.key}_factor` as keyof StockReasoning
          const aiBlurb = reasoning?.[reasoningKey] as string | undefined
          return (
            <div key={f.key} className="border-b border-border-dim pb-4 last:border-b-0">
              <div className="flex items-baseline justify-between">
                <div className="flex items-baseline gap-2">
                  <span className="num text-[12px] font-bold text-ink">{f.label}</span>
                  <span className={cn('num text-[10px] font-bold tracking-widest', interp.tone)}>
                    {interp.label}
                  </span>
                </div>
                <div className="flex items-baseline gap-3">
                  <span className="num text-[11px] text-muted">{f.raw(candidate)}</span>
                  <span className={cn('num text-[13px] font-semibold', interp.tone)}>
                    {z == null ? '—' : `${z >= 0 ? '+' : ''}${z.toFixed(2)}σ`}
                  </span>
                </div>
              </div>
              <div className="my-1.5">
                <ZBar z={z} />
              </div>
              <p className="font-sans text-[11px] leading-relaxed text-faint">
                {aiBlurb ?? (
                  <>{f.blurb}<span className="ml-1 text-muted/70">— {f.source}</span></>
                )}
              </p>
              <ResearchSnippet research={research} factor={f.key} />
            </div>
          )
        })}
      </div>

      {/* Who else is in this name */}
      <SmartMoneyPanel ticker={candidate.ticker} />
    </div>
  )
}

// ── "Who else is in this name" — congress + 13F for one ticker ─────────────────

function SmartMoneyPanel({ ticker }: { ticker: string }) {
  const { data: congress } = useCongress(ticker, 365)
  const { data: funds } = useFunds(ticker)
  const trades = congress?.trades ?? []
  const moves = funds?.moves ?? []

  if (trades.length === 0 && moves.length === 0) {
    return (
      <div className="space-y-2">
        <span className="label block">WHO ELSE IS IN THIS NAME</span>
        <p className="font-sans text-[11px] text-faint">
          No congressional or tracked-institutional activity in {ticker} on file.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <span className="label block">WHO ELSE IS IN THIS NAME</span>

      {moves.length > 0 && (
        <div className="space-y-1.5">
          <span className="num text-[10px] tracking-widest text-cyan/70">INSTITUTIONAL (13F)</span>
          {moves.slice(0, 5).map((m, i) => (
            <div key={`f-${i}`} className="flex items-center justify-between border-l-2 border-cyan/30 pl-2">
              <span className="font-sans text-[11px] text-ink">{m.manager}</span>
              <span className="num text-[10px]">
                <span className={m.action === 'NEW' ? 'text-up' : 'text-cyan'}>{m.action}</span>
                <span className="ml-2 text-muted">
                  {m.action === 'NEW'
                    ? 'new position'
                    : m.pct_change != null ? `+${(m.pct_change * 100).toFixed(0)}%` : ''}
                </span>
              </span>
            </div>
          ))}
        </div>
      )}

      {trades.length > 0 && (
        <div className="space-y-1.5">
          <span className="num text-[10px] tracking-widest text-warn/70">CONGRESS (last 12mo)</span>
          {trades.slice(0, 5).map((t, i) => (
            <div key={`c-${i}`} className="flex items-center justify-between border-l-2 border-warn/30 pl-2">
              <span className="font-sans text-[11px] text-ink">{t.senator}</span>
              <span className="num text-[10px]">
                <span className={t.transaction_type.toLowerCase().includes('purchase') ? 'text-up' : 'text-down'}>
                  {t.transaction_type}
                </span>
                <span className="ml-2 text-muted">{t.amount}</span>
              </span>
            </div>
          ))}
        </div>
      )}
      <p className="font-sans text-[10px] text-faint">
        Disclosure-lagged signals — congressional filings up to 45 days late, 13F quarterly. Context, not timing.
      </p>
    </div>
  )
}

// ── Case tab (auto-built investment case) ──────────────────────────────────────

function CasePointRow({ point, kind }: { point: CasePoint; kind: 'bull' | 'risk' }) {
  const accent = kind === 'bull' ? 'border-up/40' : 'border-down/40'
  const zTone = kind === 'bull' ? 'text-up' : 'text-down'
  const name = point.citation?.replace(/^\[\[|\]\]$/g, '').split('/').pop() ?? null
  return (
    <div className={cn('border-l-2 pl-3', accent)}>
      <div className="flex items-baseline justify-between">
        <span className="num text-[12px] font-bold text-ink">{point.label}</span>
        <div className="flex items-baseline gap-2">
          <span className="num text-[10px] text-muted">{point.stat}</span>
          <span className={cn('num text-[12px] font-semibold', zTone)}>
            {point.z >= 0 ? '+' : ''}{point.z.toFixed(2)}σ
          </span>
        </div>
      </div>
      <p className="mt-0.5 font-sans text-[12px] leading-relaxed text-muted">{point.argument}</p>
      {name && point.citation_text && (
        <div className="mt-1.5 bg-cyan/[0.03] py-1 pl-2 pr-2">
          <span className="num text-[9px] tracking-widest text-cyan/70">FROM VAULT · {name}</span>
          <p className="font-sans text-[10px] leading-snug text-faint">{point.citation_text.slice(0, 180)}…</p>
        </div>
      )}
    </div>
  )
}

function CaseTab({ ticker }: { ticker: string }) {
  const { data: caseData, isLoading } = useCase(ticker)

  if (isLoading) {
    return (
      <div className="flex items-center justify-center p-12">
        <span className="num text-sm text-muted">BUILDING CASE…</span>
      </div>
    )
  }
  if (!caseData) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 p-12 text-center">
        <span className="num text-sm text-muted">NO CASE AVAILABLE</span>
        <p className="max-w-md font-sans text-[12px] leading-relaxed text-faint">
          {ticker} isn't in the latest CORTEX discovery run, so there's no
          auto-built case. Run <code className="font-mono text-cyan">wst discover</code> to score it.
        </p>
      </div>
    )
  }

  const comp = caseData.composite_score
  const compTone = comp >= 0.5 ? 'text-up' : comp >= 0 ? 'text-warn' : 'text-down'

  return (
    <div className="overflow-y-auto p-6 space-y-6">
      <div className="space-y-1">
        <span className="font-sans text-[15px] font-semibold text-cyan">{caseData.headline}</span>
        <p className="font-sans text-[13px] leading-relaxed text-ink border-l-2 border-cyan/50 pl-3">
          {caseData.summary}
        </p>
      </div>

      <div className="flex items-stretch gap-4">
        <div className="flex flex-col justify-center border border-border bg-bg-row px-4 py-2">
          <span className="label block text-faint" style={{ fontSize: '9px' }}>COMPOSITE</span>
          <span className={cn('num text-2xl font-bold leading-none', compTone)}>
            {comp >= 0 ? '+' : ''}{comp.toFixed(2)}<span className="text-sm">σ</span>
          </span>
          <span className="num mt-0.5 text-[10px] text-faint">RANK #{caseData.composite_rank}</span>
        </div>
        <div className="flex flex-1 flex-col justify-center gap-1.5">
          <ConvBar value={caseData.suggested_conviction} />
          <span className="font-sans text-[10px] text-faint">CORTEX-suggested conviction</span>
          <span className={cn('num text-[10px] font-bold', caseData.trend_ok ? 'text-up' : 'text-down')}>
            {caseData.trend_ok ? '✓ ABOVE 200-DAY TREND' : '✕ BELOW 200-DAY TREND'}
          </span>
        </div>
      </div>

      {caseData.bull_points.length > 0 && (
        <div className="space-y-3">
          <span className="label block text-up">THE CASE FOR IT</span>
          {caseData.bull_points.map(p => <CasePointRow key={p.factor} point={p} kind="bull" />)}
        </div>
      )}

      {caseData.risk_points.length > 0 && (
        <div className="space-y-3">
          <span className="label block text-down">THE CASE AGAINST</span>
          {caseData.risk_points.map(p => <CasePointRow key={p.factor} point={p} kind="risk" />)}
        </div>
      )}

      <div className="space-y-1.5">
        <span className="label block text-warn">WHAT WOULD KILL IT</span>
        <p className="font-sans text-[12px] leading-relaxed text-muted border-l-2 border-warn/40 pl-3">
          {caseData.falsifier}
        </p>
      </div>
    </div>
  )
}

// ── Main modal ─────────────────────────────────────────────────────────────────

export function StockModal({
  ticker,
  thesis,
  onClose,
}: {
  ticker: string
  thesis?: Thesis
  onClose: () => void
}) {
  const lead = ticker
  const hasThesis = thesis != null
  const [tab, setTab] = useState<Tab>('overview')
  const [reasoning, setReasoning] = useState<StockReasoning | null>(null)
  const generateReasoning = useGenerateReasoning()
  const { data: ctx } = useTickerContext(lead)
  const { data: barsYear = [] } = useHistory(lead, '1y')
  const { data: candidate, isLoading: candLoading } = useCandidate(lead)
  const { data: research } = useTickerResearch(lead)
  const market = ctx?.market
  const price = market?.price ?? null
  const change = market?.day_change_percent ?? null
  const up = (change ?? 0) >= 0
  const factors = thesis ? computeFactors(thesis, market) : null
  const pnl =
    thesis?.entry_price != null && price != null
      ? ((price - thesis.entry_price) / thesis.entry_price) * 100
      : null

  // Plain-English quick-read
  const closes = barsYear.map(b => b.close)
  const rsiVals = computeRSI(closes)
  const currentRSI = rsiVals[rsiVals.length - 1] ?? null
  const trend = price != null && barsYear.length >= 50 ? getTrendContext(barsYear, price) : null

  const quickRead = [
    trend ? `Currently in ${trend.label.toLowerCase()}.` : null,
    currentRSI != null
      ? currentRSI > 65
        ? 'Momentum is stretched — short-term pullback risk is elevated.'
        : currentRSI < 35
          ? 'Aggressively sold recently — verify the catalyst before acting.'
          : 'Momentum is balanced.'
      : null,
    pnl != null
      ? `Your position is ${pnl >= 0 ? 'up' : 'down'} ${Math.abs(pnl).toFixed(1)}% from entry.`
      : null,
  ].filter(Boolean).join(' ')

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  useEffect(() => {
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = '' }
  }, [])

  const TABS: { id: Tab; label: string; sub: string }[] = [
    { id: 'overview', label: 'OVERVIEW', sub: 'Trend, momentum, news' },
    { id: 'case',     label: 'CASE',     sub: 'The auto-built argument' },
    { id: 'cortex',   label: 'CORTEX',   sub: '6-factor + vault research' },
    { id: 'charts',   label: 'CHARTS',   sub: 'Price, volume, RSI' },
    ...(hasThesis
      ? [{ id: 'thesis' as Tab, label: 'THESIS', sub: 'Your thesis & signal' }]
      : []),
  ]

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-bg/88 p-6 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="flex w-full max-w-6xl flex-col overflow-hidden border border-border bg-bg-panel shadow-2xl"
        style={{ height: 'calc(100vh - 48px)' }}
        onClick={e => e.stopPropagation()}
      >
        {/* ── Header ── */}
        <div className="flex shrink-0 items-start justify-between border-b border-border px-6 py-3">
          <div className="flex flex-col gap-1">
            {/* Ticker + price row */}
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-3">
                <TickerLogo ticker={lead} website={market?.website} size={40} />
                <div className="flex flex-col gap-0.5">
                  <div className="flex items-center gap-2">
                    {hasThesis ? (
                      <span className={cn('h-2 w-2 rounded-full', STATUS_DOT[thesis.status] ?? 'bg-muted')} />
                    ) : (
                      <span className="num text-[9px] tracking-widest text-cyan/70">CANDIDATE</span>
                    )}
                    <span className="num text-2xl font-bold text-ink">{lead}</span>
                    {hasThesis && thesis.tickers.length > 1 && (
                      <span className="num text-sm text-faint">
                        +{thesis.tickers.slice(1).join(' ')}
                      </span>
                    )}
                  </div>
                  {market?.company_name && (
                    <span className="text-[11px] text-muted">{market.company_name}</span>
                  )}
                </div>
              </div>
              {price != null && (
                <div className="flex items-center gap-2.5">
                  <span className={cn('num text-xl font-semibold', up ? 'text-up' : 'text-down')}>
                    {fmtPrice(price)}
                  </span>
                  <span className={cn('num flex items-center gap-0.5 text-sm', up ? 'text-up' : 'text-down')}>
                    {up ? <TrendingUp className="h-3.5 w-3.5" /> : <TrendingDown className="h-3.5 w-3.5" />}
                    {fmtSignedPercent(change)}
                  </span>
                  {pnl != null && (
                    <span className={cn(
                      'num border px-1.5 py-0.5 text-[10px]',
                      pnl >= 0 ? 'border-up/30 text-up' : 'border-down/30 text-down',
                    )}>
                      {pnl >= 0 ? '+' : ''}{pnl.toFixed(2)}% vs entry
                    </span>
                  )}
                  {factors ? (
                    <ScorePill score={factors.total} />
                  ) : candidate ? (
                    <span className={cn(
                      'num inline-flex items-center rounded-sm border px-1.5 py-0.5 text-[10px] font-bold',
                      candidate.composite_score >= 0.5 ? 'text-up bg-up/10 border-up/25'
                      : candidate.composite_score >= 0 ? 'text-warn bg-warn/10 border-warn/25'
                      : 'text-muted bg-border/40 border-border',
                    )}>
                      {candidate.composite_score >= 0 ? '+' : ''}{candidate.composite_score.toFixed(2)}σ
                    </span>
                  ) : null}
                </div>
              )}
            </div>
            {/* Quick read */}
            {quickRead && (
              <p className="font-sans text-[11px] text-muted max-w-2xl">{quickRead}</p>
            )}
          </div>
          <div className="flex items-center gap-4">
            <button
              onClick={() =>
                generateReasoning.mutate(lead, {
                  onSuccess: data => setReasoning(data),
                })
              }
              disabled={generateReasoning.isPending}
              className={cn(
                'num flex items-center gap-1.5 border px-2.5 py-1 text-[10px] tracking-widest transition-colors',
                reasoning
                  ? 'border-cyan/40 text-cyan hover:border-cyan/70'
                  : 'border-border text-muted hover:border-cyan/40 hover:text-cyan',
                generateReasoning.isPending && 'cursor-wait opacity-60',
              )}
            >
              <Sparkles className="h-3 w-3" />
              {generateReasoning.isPending ? 'GENERATING…' : reasoning ? 'REGENERATE' : 'AI REASONING'}
            </button>
            {hasThesis ? (
              <Link
                to={`/thesis/${thesis.id}`}
                className="num flex items-center gap-1 text-[10px] tracking-widest text-muted transition-colors hover:text-cyan"
                onClick={onClose}
              >
                FULL THESIS <ArrowUpRight className="h-3 w-3" />
              </Link>
            ) : (
              <Link
                to={`/new?ticker=${lead}`}
                className="num flex items-center gap-1 text-[10px] tracking-widest text-cyan transition-colors hover:text-cyan/70"
                onClick={onClose}
              >
                TRACK THIS CASE <ArrowUpRight className="h-3 w-3" />
              </Link>
            )}
            <button onClick={onClose} className="text-muted transition-colors hover:text-ink">
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* ── Tab nav ── */}
        <div className="flex shrink-0 items-stretch border-b border-border">
          {TABS.map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={cn(
                'flex flex-col items-start border-r border-border px-5 py-2.5 transition-colors',
                tab === t.id
                  ? 'border-b-2 border-b-cyan bg-bg-selected text-cyan'
                  : 'text-muted hover:bg-bg-hover hover:text-ink',
              )}
            >
              <span className={cn('num text-[11px] font-bold tracking-widest', tab === t.id ? 'text-cyan' : 'text-muted')}>
                {t.label}
              </span>
              <span className="font-sans text-[10px] text-faint">{t.sub}</span>
            </button>
          ))}
        </div>

        {/* ── Tab content ── */}
        <div className="min-h-0 flex-1 overflow-hidden">
          {tab === 'overview' && (
            <OverviewTab thesis={thesis} bars={barsYear} market={market} ctx={ctx} reasoning={reasoning} />
          )}
          {tab === 'case' && (
            <CaseTab ticker={lead} />
          )}
          {tab === 'cortex' && (
            <CortexTab candidate={candidate} research={research} loading={candLoading} reasoning={reasoning} />
          )}
          {tab === 'charts' && (
            <ChartsTab thesis={thesis} ticker={lead} />
          )}
          {tab === 'thesis' && hasThesis && (
            <ThesisTab thesis={thesis} market={market} factors={factors ?? computeFactors(thesis, market)} candidate={candidate} />
          )}
        </div>
      </div>
    </div>
  )
}
