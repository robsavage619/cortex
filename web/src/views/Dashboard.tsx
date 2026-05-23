import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Activity,
  ArrowUpRight,
  ChevronRight,
  Clock,
  Eye,
  TrendingDown,
  TrendingUp,
  X,
  Zap,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

import { PriceChart } from '@/components/charts/PriceChart'
import { Sparkline } from '@/components/charts/Sparkline'
import { useCalibration, useHistory, useReviewQueue, useTheses, useTickerContext } from '@/lib/api'
import type { MarketContext, Thesis } from '@/lib/types'
import { cn, daysUntil, fmtDate, fmtPrice, fmtSignedPercent } from '@/lib/utils'

// ── Signal scoring ─────────────────────────────────────────────────────────────
// Multi-factor model: conviction (40) + value zone (25) + momentum (20) + research (15)

interface SignalFactors {
  conviction: number  // 0–40
  valueZone: number   // 0–25
  momentum: number    // 0–20
  research: number    // 0–15
  total: number       // 0–100
}

function computeFactors(thesis: Thesis, market: MarketContext | undefined): SignalFactors {
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

// ── Shared primitives ──────────────────────────────────────────────────────────

const STATUS_DOT: Record<string, string> = {
  open: 'bg-open',
  pending: 'bg-warn',
  confirmed: 'bg-up',
  invalidated: 'bg-down',
  closed: 'bg-muted',
}
const STATUS_TEXT: Record<string, string> = {
  open: 'text-open',
  pending: 'text-warn',
  confirmed: 'text-up',
  invalidated: 'text-down',
  closed: 'text-muted',
}

function ScorePill({ score }: { score: number }) {
  const cls =
    score >= 70
      ? 'text-up bg-up/10 border-up/25'
      : score >= 50
        ? 'text-warn bg-warn/10 border-warn/25'
        : 'text-muted bg-border/40 border-border'
  return (
    <span className={cn('num inline-flex items-center rounded-sm border px-1.5 py-0.5 text-[10px] font-bold tabular-nums', cls)}>
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
                ? value >= 4
                  ? 'bg-up'
                  : value === 3
                    ? 'bg-warn'
                    : 'bg-open/60'
                : 'bg-border',
            )}
          />
        ))}
      </div>
      <span className="num text-[10px] text-faint">{value}/5</span>
    </div>
  )
}

function RangeBar({
  low,
  high,
  current,
  entry,
}: {
  low: number
  high: number
  current: number
  entry?: number | null
}) {
  const range = high - low
  if (range <= 0) return null
  const pct = Math.max(0, Math.min(100, ((current - low) / range) * 100))
  const entryPct = entry != null ? Math.max(0, Math.min(100, ((entry - low) / range) * 100)) : null
  return (
    <div className="relative h-1 w-full bg-border">
      <div className="absolute inset-y-0 left-0 bg-cyan/40" style={{ width: `${pct}%` }} />
      {entryPct != null && (
        <div
          className="absolute top-1/2 h-2.5 w-px -translate-y-1/2 bg-warn"
          style={{ left: `${entryPct}%` }}
        />
      )}
      <div
        className="absolute top-1/2 h-3 w-1 -translate-x-1/2 -translate-y-1/2 bg-cyan"
        style={{ left: `${pct}%` }}
      />
    </div>
  )
}

function SectionHeader({
  icon: Icon,
  label,
  count,
  accent,
}: {
  icon: LucideIcon
  label: string
  count?: number
  accent?: boolean
}) {
  return (
    <div className="flex shrink-0 items-center gap-2 border-b border-border bg-bg-panel px-5 py-2">
      <Icon className={cn('h-3 w-3', accent ? 'text-cyan' : 'text-muted')} />
      <span className={cn('label', accent && 'text-cyan')}>{label}</span>
      {count !== undefined && (
        <span className="num text-[10px] text-faint">({count})</span>
      )}
      <div
        className={cn(
          'ml-1 flex-1 border-t border-dashed',
          accent ? 'border-cyan/20' : 'border-border-dim',
        )}
      />
    </div>
  )
}

// ── KPI strip ──────────────────────────────────────────────────────────────────

function KpiTile({
  label,
  value,
  sub,
  tone,
}: {
  label: string
  value: string | number
  sub?: string
  tone?: 'up' | 'down' | 'warn' | 'cyan' | 'open' | 'muted'
}) {
  const colors: Record<string, string> = {
    up: 'text-up',
    down: 'text-down',
    warn: 'text-warn',
    cyan: 'text-cyan',
    open: 'text-open',
    muted: 'text-muted',
  }
  return (
    <div className="flex flex-col gap-0.5 border-r border-border px-4 py-2.5 last:border-r-0">
      <span className="label">{label}</span>
      <span className={cn('num text-2xl font-semibold leading-none', colors[tone ?? 'muted'])}>
        {value}
      </span>
      {sub && <span className="num mt-0.5 text-[10px] text-faint">{sub}</span>}
    </div>
  )
}

// ── Full-screen stock detail modal ─────────────────────────────────────────────

const PERIODS = ['1mo', '3mo', '6mo', '1y'] as const
type Period = (typeof PERIODS)[number]
const PERIOD_LABELS: Record<Period, string> = { '1mo': '1M', '3mo': '3M', '6mo': '6M', '1y': '1Y' }

function FactorBar({ label, score, max }: { label: string; score: number; max: number }) {
  return (
    <div className="space-y-0.5">
      <div className="flex items-center justify-between">
        <span className="label" style={{ fontSize: '9px' }}>{label}</span>
        <span className="num text-[9px] text-muted">{Math.round(score)}/{max}</span>
      </div>
      <div className="h-0.5 w-full bg-border">
        <div
          className="h-0.5 bg-cyan/60"
          style={{ width: `${(score / max) * 100}%` }}
        />
      </div>
    </div>
  )
}

function StockDetailModal({ thesis, onClose }: { thesis: Thesis; onClose: () => void }) {
  const lead = thesis.tickers[0] ?? ''
  const [period, setPeriod] = useState<Period>('6mo')
  const { data: ctx } = useTickerContext(lead)
  const { data: bars } = useHistory(lead, period)
  const market = ctx?.market
  const price = market?.price ?? null
  const change = market?.day_change_percent ?? null
  const up = (change ?? 0) >= 0
  const days = daysUntil(thesis.review_date)
  const overdue = days < 0
  const factors = computeFactors(thesis, market)
  const pnl =
    thesis.entry_price != null && price != null
      ? ((price - thesis.entry_price) / thesis.entry_price) * 100
      : null

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  // Prevent body scroll while modal is open
  useEffect(() => {
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = '' }
  }, [])

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-bg/85 p-8 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="relative flex w-full max-w-5xl flex-col overflow-hidden border border-border bg-bg-panel shadow-2xl"
        onClick={e => e.stopPropagation()}
      >
        {/* Modal header */}
        <div className="flex shrink-0 items-center justify-between border-b border-border px-6 py-3">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <span className={cn('h-2 w-2 rounded-full', STATUS_DOT[thesis.status] ?? 'bg-muted')} />
              <span className="num text-2xl font-bold text-ink">{lead}</span>
              {thesis.tickers.length > 1 && (
                <span className="num text-sm text-faint">+{thesis.tickers.slice(1).join(' ')}</span>
              )}
            </div>
            {price != null && (
              <div className="flex items-center gap-2">
                <span className={cn('num text-lg font-semibold', up ? 'text-up' : 'text-down')}>
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
              </div>
            )}
            <ScorePill score={factors.total} />
          </div>
          <div className="flex items-center gap-4">
            <Link
              to={`/thesis/${thesis.id}`}
              className="num flex items-center gap-1 text-[10px] tracking-widest text-muted hover:text-cyan transition-colors"
              onClick={onClose}
            >
              FULL THESIS <ArrowUpRight className="h-3 w-3" />
            </Link>
            <button onClick={onClose} className="text-muted transition-colors hover:text-ink">
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Modal body */}
        <div className="flex overflow-hidden" style={{ maxHeight: 'calc(100vh - 200px)' }}>

          {/* Left: chart + market context */}
          <div className="flex flex-1 flex-col overflow-y-auto min-w-0">

            {/* Period selector */}
            <div className="flex shrink-0 items-center gap-px border-b border-border px-4 py-1.5">
              {PERIODS.map(p => (
                <button
                  key={p}
                  onClick={() => setPeriod(p)}
                  className={cn(
                    'num px-3 py-1 text-[10px] font-semibold tracking-widest transition-colors',
                    period === p
                      ? 'border-b border-cyan text-cyan'
                      : 'text-muted hover:text-ink',
                  )}
                >
                  {PERIOD_LABELS[p]}
                </button>
              ))}
            </div>

            {/* Price chart */}
            <div className="shrink-0 border-b border-border">
              <PriceChart bars={bars ?? []} entryPrice={thesis.entry_price} height={200} />
            </div>

            {/* Market context */}
            {market && (
              <div className="flex-1 overflow-y-auto p-5 space-y-5">
                <span className="label block">MARKET CONTEXT</span>

                {/* 52W range gauge */}
                {market.week_52_low != null &&
                  market.week_52_high != null &&
                  price != null && (
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="label text-faint">52W RANGE</span>
                      <span className="num text-[10px] text-muted">
                        {fmtPrice(market.week_52_low)} — {fmtPrice(market.week_52_high)}
                      </span>
                    </div>
                    <RangeBar
                      low={market.week_52_low}
                      high={market.week_52_high}
                      current={price}
                      entry={thesis.entry_price}
                    />
                    <div className="flex items-center justify-between">
                      <span className="num text-[9px] text-faint">
                        {(
                          ((price - market.week_52_low) /
                            (market.week_52_high - market.week_52_low)) *
                          100
                        ).toFixed(0)}
                        % of annual range
                      </span>
                      {thesis.entry_price != null && (
                        <span className="num text-[9px] text-warn">
                          ▏ entry {fmtPrice(thesis.entry_price)}
                        </span>
                      )}
                    </div>
                  </div>
                )}

                <div className="grid grid-cols-3 gap-2">
                  {market.pe_ratio != null && (
                    <div className="border border-border p-3">
                      <span className="label block text-faint">P/E RATIO</span>
                      <span className="num text-base font-semibold text-ink">
                        {market.pe_ratio.toFixed(1)}×
                      </span>
                    </div>
                  )}
                  {market.market_cap != null && (
                    <div className="border border-border p-3">
                      <span className="label block text-faint">MARKET CAP</span>
                      <span className="num text-base font-semibold text-ink">
                        {market.market_cap >= 1e12
                          ? `$${(market.market_cap / 1e12).toFixed(1)}T`
                          : market.market_cap >= 1e9
                            ? `$${(market.market_cap / 1e9).toFixed(0)}B`
                            : `$${(market.market_cap / 1e6).toFixed(0)}M`}
                      </span>
                    </div>
                  )}
                  {price != null && (
                    <div className="border border-border p-3">
                      <span className="label block text-faint">LIVE PRICE</span>
                      <span className={cn('num text-base font-semibold', up ? 'text-up' : 'text-down')}>
                        {fmtPrice(price)}
                      </span>
                    </div>
                  )}
                </div>

                {/* News */}
                {market.news_headlines && market.news_headlines.length > 0 && (
                  <div className="space-y-2">
                    <span className="label block">RECENT NEWS</span>
                    {market.news_headlines.slice(0, 5).map((h, i) => (
                      <div key={i} className="flex gap-2.5 border-l-2 border-border pl-3">
                        <p className="font-sans text-[11px] text-muted leading-snug">{h}</p>
                      </div>
                    ))}
                  </div>
                )}

                {/* Senate trades */}
                {ctx?.senate_trades && ctx.senate_trades.length > 0 && (
                  <div className="space-y-2">
                    <span className="label block">SENATE ACTIVITY</span>
                    {ctx.senate_trades.slice(0, 4).map((t, i) => (
                      <div key={i} className="flex items-center justify-between border-b border-border-dim pb-1.5">
                        <span className="font-sans text-[11px] text-ink">{t.senator}</span>
                        <div className="flex items-center gap-2">
                          <span
                            className={cn(
                              'num text-[10px] font-semibold',
                              t.transaction_type.toLowerCase().includes('purchase')
                                ? 'text-up'
                                : 'text-down',
                            )}
                          >
                            {t.transaction_type}
                          </span>
                          {t.amount && (
                            <span className="num text-[10px] text-muted">{t.amount}</span>
                          )}
                          {t.transaction_date && (
                            <span className="num text-[9px] text-faint">{t.transaction_date}</span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Right: thesis details + signal breakdown */}
          <div className="w-[300px] shrink-0 overflow-y-auto border-l border-border p-5 space-y-5">

            {/* Status + conviction */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className={cn('num text-xs font-bold tracking-widest', STATUS_TEXT[thesis.status] ?? 'text-muted')}>
                  {thesis.status.toUpperCase()}
                </span>
                <ScorePill score={factors.total} />
              </div>
              <div>
                <span className="label block mb-1.5">CONVICTION</span>
                <ConvBar value={thesis.conviction} />
              </div>
            </div>

            {/* Thesis claim */}
            <div className="space-y-1.5">
              <span className="label block">THESIS</span>
              <p className="border-l-2 border-cyan/40 pl-3 font-sans text-[12px] leading-relaxed text-ink">
                {thesis.claim}
              </p>
            </div>

            {/* Falsifier */}
            <div className="space-y-1.5">
              <span className="label block">INVALIDATED IF</span>
              <p className="border-l-2 border-down/30 pl-3 font-sans text-[12px] leading-relaxed text-muted">
                {thesis.falsifier}
              </p>
            </div>

            {/* Pre-commitment fields */}
            {thesis.why_now && (
              <div className="space-y-1.5">
                <span className="label block">WHY NOW</span>
                <p className="font-sans text-[11px] leading-relaxed text-muted">{thesis.why_now}</p>
              </div>
            )}
            {thesis.base_rate && (
              <div className="space-y-1.5">
                <span className="label block">BASE RATE</span>
                <p className="font-sans text-[11px] leading-relaxed text-muted">{thesis.base_rate}</p>
              </div>
            )}
            {thesis.pre_mortem && (
              <div className="space-y-1.5">
                <span className="label block">PRE-MORTEM</span>
                <p className="font-sans text-[11px] leading-relaxed text-muted">{thesis.pre_mortem}</p>
              </div>
            )}

            {/* Timeline */}
            <div className="space-y-2 border-t border-border pt-4">
              <div className="flex items-center justify-between">
                <span className="label">REVIEW</span>
                <div className="text-right">
                  <span className="num block text-[11px] text-ink">{fmtDate(thesis.review_date)}</span>
                  <span className={cn('num text-[10px]', overdue ? 'text-down' : days <= 7 ? 'text-warn' : 'text-faint')}>
                    {overdue
                      ? `${Math.abs(days)}d OVERDUE`
                      : days === 0
                        ? 'TODAY'
                        : `${days}d remaining`}
                  </span>
                </div>
              </div>
              {thesis.entry_price != null && (
                <div className="flex items-center justify-between">
                  <span className="label">ENTRY</span>
                  <span className="num text-[11px] text-ink">{fmtPrice(thesis.entry_price)}</span>
                </div>
              )}
              <div className="flex items-center justify-between">
                <span className="label">AUTHOR</span>
                <span className="num text-[11px] text-muted">{thesis.author.toUpperCase()}</span>
              </div>
            </div>

            {/* Signal breakdown */}
            <div className="space-y-2.5 border-t border-border pt-4">
              <span className="label block">SIGNAL BREAKDOWN</span>
              <FactorBar label="CONVICTION" score={factors.conviction} max={40} />
              <FactorBar label="VALUE ZONE" score={factors.valueZone} max={25} />
              <FactorBar label="MOMENTUM" score={factors.momentum} max={20} />
              <FactorBar label="RESEARCH QUALITY" score={factors.research} max={15} />
              <div className="flex items-center justify-between border-t border-border pt-2">
                <span className="label">COMPOSITE SCORE</span>
                <ScorePill score={factors.total} />
              </div>
            </div>

            {/* CTA */}
            <Link
              to={`/thesis/${thesis.id}`}
              onClick={onClose}
              className="num flex w-full items-center justify-center gap-2 border border-cyan py-2 text-[11px] font-semibold tracking-widest text-cyan transition-colors hover:bg-cyan hover:text-bg"
            >
              OPEN FULL THESIS →
            </Link>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Signal card (alpha signals section) ────────────────────────────────────────

function SignalCard({ thesis, onClick }: { thesis: Thesis; onClick: () => void }) {
  const lead = thesis.tickers[0] ?? ''
  const { data: ctx, isLoading } = useTickerContext(lead)
  const { data: histData } = useHistory(lead, '3mo')
  const market = ctx?.market
  const price = market?.price ?? null
  const change = market?.day_change_percent ?? null
  const up = (change ?? 0) >= 0
  const closes = histData?.map(b => b.close) ?? []
  const factors = computeFactors(thesis, market)
  const pnl =
    thesis.entry_price != null && price != null
      ? ((price - thesis.entry_price) / thesis.entry_price) * 100
      : null
  const days = daysUntil(thesis.review_date)
  const overdue = days < 0

  return (
    <button
      onClick={onClick}
      className="group relative flex w-[252px] shrink-0 flex-col gap-3 border border-border bg-bg-row p-4 text-left transition-all hover:border-cyan/40 hover:bg-bg-hover"
    >
      {/* Score top-right */}
      <div className="absolute right-3 top-3">
        <ScorePill score={factors.total} />
      </div>

      {/* Ticker */}
      <div className="flex items-center gap-1.5 pr-10">
        <span className={cn('h-1.5 w-1.5 rounded-full', STATUS_DOT[thesis.status] ?? 'bg-muted')} />
        <span className="num text-xl font-bold text-ink">{lead}</span>
        {thesis.tickers.length > 1 && (
          <span className="num text-[10px] text-faint">+{thesis.tickers.slice(1).join(' ')}</span>
        )}
      </div>

      {/* Price */}
      <div className="flex items-baseline gap-2">
        {isLoading ? (
          <span className="num text-sm text-faint">loading…</span>
        ) : price != null ? (
          <>
            <span className={cn('num text-[15px] font-semibold', up ? 'text-up' : 'text-down')}>
              {fmtPrice(price)}
            </span>
            <span className={cn('num text-[11px]', up ? 'text-up/70' : 'text-down/70')}>
              {fmtSignedPercent(change)}
            </span>
          </>
        ) : (
          <span className="num text-sm text-faint">—</span>
        )}
      </div>
      {pnl != null && (
        <span className={cn('num -mt-2 text-[10px]', pnl >= 0 ? 'text-up' : 'text-down')}>
          {pnl >= 0 ? '+' : ''}{pnl.toFixed(1)}% vs entry {fmtPrice(thesis.entry_price)}
        </span>
      )}

      {/* Sparkline */}
      {closes.length >= 4 && (
        <div className="border-b border-border-dim pb-3">
          <Sparkline values={closes} width={220} height={38} />
        </div>
      )}

      {/* Conviction */}
      <ConvBar value={thesis.conviction} />

      {/* Claim */}
      <p className="line-clamp-2 font-sans text-[11px] leading-snug text-muted">
        {thesis.claim}
      </p>

      {/* 52W range */}
      {market?.week_52_low != null && market.week_52_high != null && price != null && (
        <div className="space-y-1">
          <RangeBar
            low={market.week_52_low}
            high={market.week_52_high}
            current={price}
            entry={thesis.entry_price}
          />
          <div className="flex items-center justify-between">
            <span className="num text-[9px] text-faint">{fmtPrice(market.week_52_low)}</span>
            <span className="num text-[9px] text-faint">52W</span>
            <span className="num text-[9px] text-faint">{fmtPrice(market.week_52_high)}</span>
          </div>
        </div>
      )}

      {/* Review date */}
      <div className="flex items-center justify-between border-t border-border-dim pt-2">
        <span className="num text-[10px] text-faint">REVIEW {fmtDate(thesis.review_date)}</span>
        <span
          className={cn(
            'num text-[10px] font-semibold',
            overdue ? 'text-down' : days <= 7 ? 'text-warn' : 'text-faint',
          )}
        >
          {overdue ? `${Math.abs(days)}d OVERDUE` : days === 0 ? 'TODAY' : `${days}d`}
        </span>
      </div>

      {/* Hover chevron */}
      <ChevronRight className="absolute bottom-3 right-3 h-3.5 w-3.5 text-cyan opacity-0 transition-opacity group-hover:opacity-100" />
    </button>
  )
}

// ── Compact thesis row ─────────────────────────────────────────────────────────

function ThesisRow({
  thesis,
  even,
  dim,
  onClick,
}: {
  thesis: Thesis
  even: boolean
  dim?: boolean
  onClick: () => void
}) {
  const lead = thesis.tickers[0] ?? ''
  const { data: ctx } = useTickerContext(lead)
  const { data: histData } = useHistory(lead, '1mo')
  const market = ctx?.market
  const price = market?.price ?? null
  const change = market?.day_change_percent ?? null
  const up = (change ?? 0) >= 0
  const closes = histData?.map(b => b.close) ?? []
  const days = daysUntil(thesis.review_date)
  const overdue = days < 0
  const pnl =
    thesis.entry_price != null && price != null
      ? ((price - thesis.entry_price) / thesis.entry_price) * 100
      : null

  return (
    <tr
      onClick={onClick}
      className={cn(
        'group cursor-pointer border-b border-border-dim transition-colors',
        even ? 'bg-bg-row hover:bg-bg-hover' : 'bg-bg-row-alt hover:bg-bg-hover',
        dim && 'opacity-50',
      )}
    >
      <td className="w-4 px-2 py-2">
        <span className={cn('inline-block h-1.5 w-1.5 rounded-full', STATUS_DOT[thesis.status] ?? 'bg-muted')} />
      </td>
      <td className="w-[72px] px-3 py-2">
        <span className="num text-[12px] font-bold text-ink">{lead}</span>
      </td>
      <td className="max-w-0 px-3 py-2">
        <span className="block truncate text-[12px] text-ink">{thesis.claim}</span>
        <span className="block truncate text-[10px] text-muted">⚡ {thesis.falsifier}</span>
      </td>
      <td className="w-20 px-2 py-2">
        <ConvBar value={thesis.conviction} />
      </td>
      <td className="w-16 px-2 py-2">
        {closes.length >= 4 ? (
          <Sparkline values={closes} width={52} height={18} />
        ) : (
          <span className="text-faint text-[10px]">—</span>
        )}
      </td>
      <td className="w-[140px] px-3 py-2">
        {price != null ? (
          <div>
            <span className={cn('num text-[11px] font-semibold', up ? 'text-up' : 'text-down')}>
              {fmtPrice(price)}{' '}
              <span className="font-normal">{fmtSignedPercent(change)}</span>
            </span>
            {pnl != null && (
              <span className={cn('num block text-[9px]', pnl >= 0 ? 'text-up' : 'text-down')}>
                {pnl >= 0 ? '+' : ''}{pnl.toFixed(1)}% vs entry
              </span>
            )}
          </div>
        ) : (
          <span className="num text-[11px] text-faint">—</span>
        )}
      </td>
      <td className="w-24 px-3 py-2">
        <span className="num block text-[10px] text-muted">{fmtDate(thesis.review_date)}</span>
        <span
          className={cn(
            'num text-[9px] font-semibold',
            overdue ? 'text-down' : days <= 7 ? 'text-warn' : 'text-faint',
          )}
        >
          {overdue ? `${Math.abs(days)}d OVERDUE` : days === 0 ? 'TODAY' : `${days}d`}
        </span>
      </td>
      <td className="w-6 px-2 py-2">
        <ChevronRight className="h-3 w-3 text-faint opacity-0 transition-opacity group-hover:opacity-100" />
      </td>
    </tr>
  )
}

function ThesisTable({
  theses,
  dim,
  onRowClick,
}: {
  theses: Thesis[]
  dim?: boolean
  onRowClick: (t: Thesis) => void
}) {
  return (
    <table className="w-full">
      <thead className="sticky top-0 z-10 bg-bg-panel">
        <tr>
          <th className="w-4 border-b border-border" />
          <th className="label w-[72px] border-b border-border px-3 py-1.5 text-left">TICKER</th>
          <th className="label border-b border-border px-3 py-1.5 text-left">THESIS</th>
          <th className="label w-20 border-b border-border px-2 py-1.5 text-left">CONVICTION</th>
          <th className="label w-16 border-b border-border px-2 py-1.5 text-left">TREND</th>
          <th className="label w-[140px] border-b border-border px-3 py-1.5 text-left">PRICE</th>
          <th className="label w-24 border-b border-border px-3 py-1.5 text-left">REVIEW</th>
          <th className="w-6 border-b border-border" />
        </tr>
      </thead>
      <tbody>
        {theses.map((t, i) => (
          <ThesisRow
            key={t.id}
            thesis={t}
            even={i % 2 === 0}
            dim={dim}
            onClick={() => onRowClick(t)}
          />
        ))}
      </tbody>
    </table>
  )
}

// ── Dashboard ──────────────────────────────────────────────────────────────────

export function Dashboard() {
  const theses = useTheses()
  const queue = useReviewQueue()
  const cal = useCalibration()
  const [modal, setModal] = useState<Thesis | null>(null)

  const all = theses.data ?? []
  const active = all.filter(t => t.status === 'open' || t.status === 'pending')
  const closed = all.filter(t =>
    t.status === 'confirmed' || t.status === 'invalidated' || t.status === 'closed',
  )
  const hits = closed.filter(t => t.status === 'confirmed').length
  const hitRate = closed.length > 0 ? `${((hits / closed.length) * 100).toFixed(0)}%` : '—'
  const due = queue.data?.length ?? 0

  // Alpha signals: highest conviction, open/pending
  const alphaTheses = active
    .filter(t => t.conviction >= 4)
    .sort((a, b) => b.conviction - a.conviction)

  // Watch: lower conviction or pending
  const watchTheses = active
    .filter(t => t.conviction < 4)
    .sort((a, b) => daysUntil(a.review_date) - daysUntil(b.review_date))

  if (theses.isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <span className="num text-sm text-muted">LOADING…</span>
      </div>
    )
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">

      {/* Modal */}
      {modal && <StockDetailModal thesis={modal} onClose={() => setModal(null)} />}

      {/* KPI strip */}
      <div className="flex shrink-0 items-stretch border-b border-border bg-bg-panel">
        <KpiTile label="ACTIVE" value={active.length} tone="open" />
        <KpiTile
          label="DUE"
          value={due}
          sub={due > 0 ? 'ACTION NEEDED' : 'ALL CLEAR'}
          tone={due > 0 ? 'warn' : 'muted'}
        />
        <KpiTile
          label="HIT RATE"
          value={hitRate}
          sub={closed.length > 0 ? `${closed.length} REVIEWED` : 'NO REVIEWS YET'}
          tone={hits > 0 ? 'up' : 'muted'}
        />
        <KpiTile
          label="BRIER"
          value={cal.data ? cal.data.brier_score.toFixed(3) : '—'}
          sub={
            cal.data?.overconfident
              ? 'OVERCONFIDENT'
              : cal.data
                ? 'CALIBRATED'
                : 'NEEDS DATA'
          }
          tone={cal.data?.overconfident ? 'warn' : 'muted'}
        />
        <KpiTile label="TOTAL" value={all.length} tone="muted" />
        <div className="ml-auto flex items-center px-4">
          <Link
            to="/new"
            className="num border border-cyan px-3 py-1.5 text-[11px] font-semibold tracking-widest text-cyan transition-colors hover:bg-cyan hover:text-bg"
          >
            + NEW THESIS
          </Link>
        </div>
      </div>

      {/* Sections */}
      <div className="flex-1 overflow-y-auto">

        {/* Review due alert */}
        {due > 0 && (
          <div className="flex shrink-0 items-center gap-3 border-b border-warn/30 bg-warn/5 px-5 py-2.5">
            <Clock className="h-3.5 w-3.5 text-warn" />
            <span className="num text-[11px] text-warn">
              {due} {due === 1 ? 'thesis' : 'theses'} due for review
            </span>
            <Link
              to="/review"
              className="num ml-auto text-[10px] tracking-widest text-warn/70 hover:text-warn transition-colors"
            >
              REVIEW NOW →
            </Link>
          </div>
        )}

        {/* ── ALPHA SIGNALS ── */}
        <div>
          <SectionHeader icon={Zap} label="ALPHA SIGNALS" count={alphaTheses.length} accent />
          {alphaTheses.length === 0 ? (
            <div className="flex items-center gap-3 px-5 py-5">
              <span className="num text-[11px] text-faint">
                No alpha signals — theses with conviction ≥ 4 will appear here with composite scoring
              </span>
            </div>
          ) : (
            <div className="overflow-x-auto border-b border-border">
              <div className="flex gap-3 p-4">
                {alphaTheses.map(t => (
                  <SignalCard key={t.id} thesis={t} onClick={() => setModal(t)} />
                ))}
              </div>
            </div>
          )}
        </div>

        {/* ── ACTIVE POSITIONS ── */}
        {watchTheses.length > 0 && (
          <div>
            <SectionHeader icon={Activity} label="ACTIVE POSITIONS" count={watchTheses.length} />
            <div className="border-b border-border">
              <ThesisTable theses={watchTheses} onRowClick={t => setModal(t)} />
            </div>
          </div>
        )}

        {/* ── RECENT CLOSES ── */}
        {closed.length > 0 && (
          <div>
            <SectionHeader icon={Eye} label="RECENT CLOSES" count={closed.length} />
            <div className="border-b border-border">
              <ThesisTable
                theses={closed.slice(0, 6)}
                dim
                onRowClick={t => setModal(t)}
              />
            </div>
          </div>
        )}

        {/* Empty state */}
        {all.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-4 py-24">
            <span className="num text-sm text-muted">NO THESES IN SYSTEM</span>
            <p className="max-w-xs text-center font-sans text-[11px] text-faint">
              Add your first investment thesis to begin tracking performance and generating
              alpha signals.
            </p>
            <Link
              to="/new"
              className="num border border-cyan px-5 py-2 text-[11px] font-semibold tracking-widest text-cyan transition-colors hover:bg-cyan hover:text-bg"
            >
              CREATE FIRST THESIS
            </Link>
          </div>
        )}

      </div>
    </div>
  )
}
