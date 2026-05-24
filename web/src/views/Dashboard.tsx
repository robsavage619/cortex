import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { ChevronRight, Clock, RefreshCw } from 'lucide-react'

import { Sparkline } from '@/components/charts/Sparkline'
import {
  useCalibration,
  useCandidates,
  useCongress,
  useFunds,
  useHistory,
  useRefresh,
  useRefreshStatus,
  useReviewQueue,
  useTheses,
  useTickerContext,
} from '@/lib/api'
import type { Candidate, MarketContext, Thesis } from '@/lib/types'
import { TickerLogo } from '@/components/ui/TickerLogo'
import { StockModal } from '@/views/StockModal'
import { cn, daysUntil, fmtDate, fmtPrice, fmtSignedPercent } from '@/lib/utils'

// ── Bucket SVG icons ───────────────────────────────────────────────────────────

function IconStrongBuy({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" className={className} fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="8" cy="8" r="6.5" />
      <circle cx="8" cy="8" r="2.5" />
      {/* arrow pointing up through center */}
      <line x1="8" y1="5.5" x2="8" y2="1" />
      <polyline points="5.5,3.5 8,1 10.5,3.5" />
    </svg>
  )
}

function IconWatch({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" className={className} fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
      <path d="M1 8 C3.5 3.5 5.5 2 8 2 C10.5 2 12.5 3.5 15 8 C12.5 12.5 10.5 14 8 14 C5.5 14 3.5 12.5 1 8 Z" />
      <circle cx="8" cy="8" r="2.2" />
      {/* circuit tick marks on the lens edge */}
      <line x1="8" y1="2" x2="8" y2="3.4" />
      <line x1="8" y1="12.6" x2="8" y2="14" />
    </svg>
  )
}

function IconMonitor({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" className={className} fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
      {/* three horizontal bars — like a hold / EKG baseline */}
      <line x1="2" y1="5" x2="14" y2="5" />
      <polyline points="2,8 5,8 6,6 7,10 8,8 14,8" />
      <line x1="2" y1="11" x2="14" y2="11" />
    </svg>
  )
}

function IconDiscovered({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" className={className} fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
      {/* radar / sonar sweep */}
      <circle cx="8" cy="8" r="6.5" />
      <circle cx="8" cy="8" r="3.5" />
      <line x1="8" y1="8" x2="13.5" y2="5" />
      <circle cx="11.5" cy="5.8" r="0.8" fill="currentColor" stroke="none" />
    </svg>
  )
}

function IconAlgoBuy({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" className={className} fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
      {/* chip with a bolt — the algorithm's actionable call */}
      <rect x="3.5" y="3.5" width="9" height="9" rx="1" />
      <line x1="6" y1="1.5" x2="6" y2="3.5" />
      <line x1="10" y1="1.5" x2="10" y2="3.5" />
      <line x1="6" y1="12.5" x2="6" y2="14.5" />
      <line x1="10" y1="12.5" x2="10" y2="14.5" />
      <line x1="1.5" y1="6" x2="3.5" y2="6" />
      <line x1="1.5" y1="10" x2="3.5" y2="10" />
      <line x1="12.5" y1="6" x2="14.5" y2="6" />
      <line x1="12.5" y1="10" x2="14.5" y2="10" />
      <polyline points="8.5,5.5 6.5,8.3 8,8.3 7.5,10.5 9.5,7.7 8,7.7" fill="currentColor" stroke="none" />
    </svg>
  )
}

function IconReview({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" className={className} fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
      {/* diamond */}
      <polygon points="8,1 15,8 8,15 1,8" />
      <line x1="8" y1="5" x2="8" y2="9.5" />
      <circle cx="8" cy="11.5" r="0.6" fill="currentColor" stroke="none" />
    </svg>
  )
}

// ── Signal scoring ─────────────────────────────────────────────────────────────

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

// ── Shared primitives ──────────────────────────────────────────────────────────

const STATUS_DOT: Record<string, string> = {
  open: 'bg-open',
  pending: 'bg-warn',
  confirmed: 'bg-up',
  invalidated: 'bg-down',
  closed: 'bg-muted',
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

type BucketTone = 'strong-buy' | 'watch' | 'monitor' | 'review' | 'default'

const TONE_COLORS: Record<BucketTone, { text: string; border: string }> = {
  'strong-buy': { text: 'text-up',   border: 'border-up/20'   },
  'watch':      { text: 'text-cyan', border: 'border-cyan/20' },
  'monitor':    { text: 'text-muted',border: 'border-border-dim' },
  'review':     { text: 'text-warn', border: 'border-warn/20' },
  'default':    { text: 'text-muted',border: 'border-border-dim' },
}

function SectionHeader({
  icon: Icon,
  label,
  sub,
  count,
  tone = 'default',
}: {
  icon: React.FC<{ className?: string }>
  label: string
  sub?: string
  count?: number
  tone?: BucketTone
}) {
  const { text, border } = TONE_COLORS[tone]
  return (
    <div className="flex shrink-0 items-center gap-2.5 border-b border-border bg-bg-panel px-5 py-2">
      <Icon className={cn('h-3.5 w-3.5', text)} />
      <span className={cn('label', text)}>{label}</span>
      {sub && <span className="font-sans text-[10px] text-faint">{sub}</span>}
      {count !== undefined && (
        <span className="num text-[10px] text-faint">({count})</span>
      )}
      <div className={cn('ml-1 flex-1 border-t border-dashed', border)} />
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

// ── Factor bar (z-score visualisation) ────────────────────────────────────────

function FactorBar({ label, z }: { label: string; z: number | null }) {
  if (z === null) {
    return (
      <div className="flex items-center gap-2">
        <span className="w-9 font-sans text-[10px] text-muted">{label}</span>
        <span className="num text-[10px] text-muted">—</span>
      </div>
    )
  }
  const clamped = Math.max(-3, Math.min(3, z))
  const pct = ((clamped + 3) / 6) * 100
  const fill = z >= 0.5 ? 'bg-up' : z >= -0.5 ? 'bg-warn' : 'bg-down'
  return (
    <div className="flex items-center gap-2">
      <span className="w-9 font-sans text-[10px] text-muted">{label}</span>
      <div className="relative h-1.5 w-16 rounded-sm bg-border-bright">
        <div
          className={cn('absolute inset-y-0 left-0 rounded-sm', fill)}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className={cn('num text-[10px] font-medium', z >= 0.5 ? 'text-up' : z >= -0.5 ? 'text-warn' : 'text-down')}>
        {z >= 0 ? '+' : ''}{z.toFixed(2)}
      </span>
    </div>
  )
}

// ── Candidate card (DISCOVERED section) ───────────────────────────────────────

function CandidateCard({ candidate, onClick }: { candidate: Candidate; onClick: () => void }) {
  const { data: ctx, isLoading } = useTickerContext(candidate.ticker)
  const { data: histData } = useHistory(candidate.ticker, '3mo')
  const market = ctx?.market
  const price = market?.price ?? null
  const change = market?.day_change_percent ?? null
  const up = (change ?? 0) >= 0
  const closes = histData?.map(b => b.close) ?? []

  const scoreColor =
    candidate.composite_score >= 0.5
      ? 'text-up bg-up/10 border-up/25'
      : candidate.composite_score >= 0
        ? 'text-warn bg-warn/10 border-warn/25'
        : 'text-muted bg-border/40 border-border'

  return (
    <button
      onClick={onClick}
      className="group relative flex w-[240px] shrink-0 flex-col gap-2.5 border border-border-bright bg-bg-panel p-4 text-left transition-all hover:border-cyan/40 hover:bg-bg-hover"
    >
      {/* rank + score */}
      <div className="absolute right-3 top-3 flex items-center gap-1">
        <span className="num text-[9px] text-faint">#{candidate.composite_rank}</span>
        <span className={cn('num inline-flex items-center rounded-sm border px-1.5 py-0.5 text-[10px] font-bold tabular-nums', scoreColor)}>
          {candidate.composite_score >= 0 ? '+' : ''}{candidate.composite_score.toFixed(2)}z
        </span>
      </div>

      {/* Logo + Ticker + Company name */}
      <div className="flex items-center gap-2.5 pr-16">
        <TickerLogo ticker={candidate.ticker} website={market?.website} size={32} className="shrink-0" />
        <div className="min-w-0">
          <div className="num text-xl font-bold leading-tight text-ink">{candidate.ticker}</div>
          {market?.company_name && (
            <div className="text-[10px] leading-tight text-faint">{market.company_name}</div>
          )}
        </div>
      </div>

      {/* Price */}
      <div className="flex items-baseline gap-2">
        {isLoading ? (
          <span className="num text-sm text-faint">loading…</span>
        ) : price != null ? (
          <>
            <span className={cn('num text-[14px] font-semibold', up ? 'text-up' : 'text-down')}>
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

      {/* Sparkline */}
      {closes.length >= 4 && (
        <div className="border-b border-border-dim pb-2.5">
          <Sparkline values={closes} width={208} height={32} />
        </div>
      )}

      {/* Factor bars */}
      <div className="space-y-1.5">
        <FactorBar label="MOM"   z={candidate.z_momentum} />
        <FactorBar label="LVOL"  z={candidate.z_low_vol} />
        <FactorBar label="SHR"   z={candidate.z_sharpe} />
        <FactorBar label="VAL"   z={candidate.z_value} />
        <FactorBar label="QUAL"  z={candidate.z_quality} />
      </div>

      {/* Open the full analysis (overview, case, cortex, charts) */}
      <span className="num mt-1 border border-cyan/50 px-2 py-1 text-center text-[10px] tracking-widest text-cyan/80 transition-colors group-hover:border-cyan group-hover:text-cyan">
        ANALYZE →
      </span>
    </button>
  )
}

// ── Sync-all-data button ───────────────────────────────────────────────────────

function SyncButton() {
  const qc = useQueryClient()
  const refresh = useRefresh()
  const [polling, setPolling] = useState(false)
  const status = useRefreshStatus(polling)
  const running = polling && (status.data?.running ?? true)

  useEffect(() => {
    if (polling && status.data && !status.data.running) {
      void qc.invalidateQueries({ queryKey: ['candidates'] })
      void qc.invalidateQueries({ queryKey: ['congress'] })
      void qc.invalidateQueries({ queryKey: ['funds'] })
      void qc.invalidateQueries({ queryKey: ['theses'] })
      void qc.invalidateQueries({ queryKey: ['ticker-context'] })
      setPolling(false)
    }
  }, [status.data, polling, qc])

  const steps = status.data?.steps ?? {}
  const activeStep =
    steps.discover === 'running' ? 'scanning S&P 500…'
    : steps.congress === 'running' ? 'syncing congress…'
    : 'starting…'

  return (
    <button
      onClick={() => { refresh.mutate(); setPolling(true) }}
      disabled={running}
      className={cn(
        'num flex items-center gap-1.5 border px-3 py-1.5 text-[11px] font-semibold tracking-widest transition-colors',
        running
          ? 'cursor-wait border-warn/40 text-warn'
          : 'border-cyan text-cyan hover:bg-cyan hover:text-bg',
      )}
      title="Re-scan the S&P 500 and pull the latest congressional filings"
    >
      <RefreshCw className={cn('h-3 w-3', running && 'animate-spin')} />
      {running ? activeStep.toUpperCase() : 'SYNC DATA'}
    </button>
  )
}

// ── Congress section ─────────────────────────────────────────────────────────

function IconCongress({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" className={className} fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
      {/* capitol dome */}
      <path d="M2 14 h12" />
      <path d="M3 14 v-4 h10 v4" />
      <path d="M5 10 v-2 M8 10 v-2 M11 10 v-2" />
      <path d="M4 8 h8" />
      <path d="M5.5 8 C5.5 5.5 8 4 8 2 C8 4 10.5 5.5 10.5 8" />
    </svg>
  )
}

function txnTone(type: string): string {
  const t = type.toLowerCase()
  if (t.includes('purchase')) return 'text-up'
  if (t.includes('sale')) return 'text-down'
  return 'text-muted'
}

function CongressSection() {
  const { data, isLoading } = useCongress(null, 120)
  const trades = data?.trades ?? []

  return (
    <div>
      <SectionHeader
        icon={IconCongress}
        label="CONGRESS"
        sub="Recent Senate disclosures (last 120d) — scraped from efdsearch.senate.gov"
        count={trades.length}
        tone="watch"
      />
      {isLoading ? (
        <div className="px-5 py-5">
          <span className="num text-[11px] text-faint">Loading congressional filings…</span>
        </div>
      ) : trades.length === 0 ? (
        <div className="border-b border-border px-5 py-5">
          <span className="num text-[11px] text-faint">
            No filings yet — run <code className="font-mono text-cyan">cortex congress-sync</code> or hit SYNC DATA
          </span>
        </div>
      ) : (
        <div className="max-h-[340px] overflow-y-auto border-b border-border">
          <table className="w-full">
            <thead className="sticky top-0 z-10 bg-bg-panel">
              <tr>
                <th className="label border-b border-border px-3 py-1.5 text-left">DISCLOSED</th>
                <th className="label border-b border-border px-3 py-1.5 text-left">SENATOR</th>
                <th className="label w-[72px] border-b border-border px-3 py-1.5 text-left">TICKER</th>
                <th className="label border-b border-border px-3 py-1.5 text-left">TYPE</th>
                <th className="label border-b border-border px-3 py-1.5 text-left">AMOUNT</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t, i) => (
                <tr
                  key={`${t.report_url}-${t.ticker}-${i}`}
                  className={cn(
                    'border-b border-border-dim',
                    i % 2 === 0 ? 'bg-bg-row' : 'bg-bg-row-alt',
                  )}
                >
                  <td className="num px-3 py-1.5 text-[10px] text-muted">
                    {t.disclosure_date ?? t.transaction_date ?? '—'}
                  </td>
                  <td className="px-3 py-1.5 text-[11px] text-ink">{t.senator}</td>
                  <td className="num px-3 py-1.5 text-[11px] font-bold text-ink">{t.ticker}</td>
                  <td className={cn('num px-3 py-1.5 text-[10px] font-semibold', txnTone(t.transaction_type))}>
                    {t.transaction_type}
                  </td>
                  <td className="num px-3 py-1.5 text-[10px] text-muted">{t.amount}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Smart-money (13F) section ───────────────────────────────────────────────

function IconFund({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" className={className} fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
      {/* bank columns */}
      <path d="M8 1.5 L14 5 H2 Z" />
      <path d="M2 5 h12" />
      <path d="M3.5 5 v6 M6.5 5 v6 M9.5 5 v6 M12.5 5 v6" />
      <path d="M2 11 h12 M1.5 13.5 h13" />
    </svg>
  )
}

function fmtBigUsd(v: number): string {
  if (v >= 1e9) return `$${(v / 1e9).toFixed(1)}B`
  if (v >= 1e6) return `$${(v / 1e6).toFixed(0)}M`
  if (v >= 1e3) return `$${(v / 1e3).toFixed(0)}K`
  return `$${v}`
}

function SmartMoneySection() {
  const { data, isLoading } = useFunds(null)
  const moves = data?.moves ?? []

  return (
    <div>
      <SectionHeader
        icon={IconFund}
        label="SMART MONEY"
        sub="Institutional 13F buys (NEW + ADD) — Wood, Buffett, Ackman, Burry, Dalio & more"
        count={moves.length}
        tone="strong-buy"
      />
      {isLoading ? (
        <div className="px-5 py-5">
          <span className="num text-[11px] text-faint">Loading 13F filings…</span>
        </div>
      ) : moves.length === 0 ? (
        <div className="border-b border-border px-5 py-5">
          <span className="num text-[11px] text-faint">
            No fund data yet — run <code className="font-mono text-cyan">cortex funds-sync</code> or hit SYNC DATA
          </span>
        </div>
      ) : (
        <div className="max-h-[360px] overflow-y-auto border-b border-border">
          <table className="w-full">
            <thead className="sticky top-0 z-10 bg-bg-panel">
              <tr>
                <th className="label w-[64px] border-b border-border px-3 py-1.5 text-left">ACTION</th>
                <th className="label w-[72px] border-b border-border px-3 py-1.5 text-left">TICKER</th>
                <th className="label border-b border-border px-3 py-1.5 text-left">MANAGER</th>
                <th className="label border-b border-border px-3 py-1.5 text-right">POSITION</th>
                <th className="label w-20 border-b border-border px-3 py-1.5 text-right">CHANGE</th>
                <th className="label w-24 border-b border-border px-3 py-1.5 text-right">AS OF</th>
              </tr>
            </thead>
            <tbody>
              {moves.map((m, i) => (
                <tr
                  key={`${m.manager}-${m.ticker}-${i}`}
                  className={cn(
                    'border-b border-border-dim',
                    i % 2 === 0 ? 'bg-bg-row' : 'bg-bg-row-alt',
                  )}
                >
                  <td className="px-3 py-1.5">
                    <span className={cn(
                      'num text-[9px] font-bold tracking-widest',
                      m.action === 'NEW' ? 'text-up' : 'text-cyan',
                    )}>
                      {m.action}
                    </span>
                  </td>
                  <td className="num px-3 py-1.5 text-[11px] font-bold text-ink">{m.ticker}</td>
                  <td className="px-3 py-1.5 text-[11px] text-muted">{m.manager}</td>
                  <td className="num px-3 py-1.5 text-right text-[10px] text-muted">{fmtBigUsd(m.value)}</td>
                  <td className="num px-3 py-1.5 text-right text-[10px] text-up">
                    {m.action === 'NEW'
                      ? 'new'
                      : m.pct_change != null
                        ? `+${(m.pct_change * 100).toFixed(0)}%`
                        : '—'}
                  </td>
                  <td className="num px-3 py-1.5 text-right text-[10px] text-faint">{m.period ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Dashboard ──────────────────────────────────────────────────────────────────

export function Dashboard() {
  const theses = useTheses()
  const queue = useReviewQueue()
  const cal = useCalibration()
  const candidatesQuery = useCandidates()
  const [modal, setModal] = useState<Thesis | null>(null)
  const [caseTicker, setCaseTicker] = useState<string | null>(null)

  const candidates = candidatesQuery.data?.candidates ?? []
  const lastRun = candidatesQuery.data?.last_run ?? null
  // The composite is an equal-weight average of five cross-sectional z-scores,
  // so its spread is compressed (≈σ/√5). Tier on its own scale rather than a
  // raw +0.75σ bar, which is far too strict for an averaged signal.
  const STRONG_CUT = 0.5  // standout, multi-factor leaders
  const BUY_CUT = 0.2     // solidly positive across the composite
  const algoStrong = candidates.filter(c => c.composite_score >= STRONG_CUT)
  const algoBuy = candidates.filter(
    c => c.composite_score >= BUY_CUT && c.composite_score < STRONG_CUT,
  )
  const algoBuys = [...algoStrong, ...algoBuy]

  const all = theses.data ?? []
  const active = all.filter(t => t.status === 'open' || t.status === 'pending')
  const closed = all.filter(t =>
    t.status === 'confirmed' || t.status === 'invalidated' || t.status === 'closed',
  )
  const hits = closed.filter(t => t.status === 'confirmed').length
  const hitRate = closed.length > 0 ? `${((hits / closed.length) * 100).toFixed(0)}%` : '—'
  const due = queue.data?.length ?? 0

  // ── Algorithm-driven buckets ──────────────────────────────────────────────
  // STRONG BUY  conviction ≥ 4 — algorithm has high confidence, act now
  // WATCH        conviction 3  — thesis is solid, waiting for entry signal
  // MONITORING   conviction ≤ 2 — active position, thesis not fully scored
  // (REVIEW NOW is cross-cutting — surfaced via the due banner + review queue)

  const strongBuy = active
    .filter(t => t.conviction >= 4)
    .sort((a, b) => b.conviction - a.conviction)

  const watch = active
    .filter(t => t.conviction === 3)
    .sort((a, b) => daysUntil(a.review_date) - daysUntil(b.review_date))

  const monitoring = active
    .filter(t => t.conviction <= 2)
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
      {modal && <StockModal ticker={modal.tickers[0] ?? ''} thesis={modal} onClose={() => setModal(null)} />}
      {caseTicker && <StockModal ticker={caseTicker} onClose={() => setCaseTicker(null)} />}

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
        <div className="ml-auto flex items-center gap-2 px-4">
          <SyncButton />
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

        {/* ── DISCOVERED ── */}
        <div>
          <SectionHeader
            icon={IconDiscovered}
            label="DISCOVERED"
            sub={lastRun ? `last run ${new Date(lastRun).toLocaleDateString()}` : 'run cortex discover to populate'}
            count={candidates.length}
            tone="watch"
          />
          {candidates.length === 0 ? (
            <div className="flex items-center gap-3 border-b border-border px-5 py-5">
              <span className="num text-[11px] text-faint">
                No candidates — run <code className="font-mono text-cyan">cortex discover</code> to screen the S&amp;P 500
              </span>
            </div>
          ) : (
            <div className="overflow-x-auto border-b border-border">
              <div className="flex gap-3 p-4">
                {candidates.map(c => (
                  <CandidateCard key={c.ticker} candidate={c} onClick={() => setCaseTicker(c.ticker)} />
                ))}
              </div>
            </div>
          )}
        </div>

        {/* ── ALGO BUYS ── */}
        {algoBuys.length > 0 && (
          <div>
            <SectionHeader
              icon={IconAlgoBuy}
              label="ALGO BUYS"
              sub="CORTEX multi-factor buys — built from the engine, not hand-picked"
              count={algoBuys.length}
              tone="strong-buy"
            />
            <div className="overflow-x-auto border-b border-border">
              <div className="flex items-stretch gap-3 p-4">
                {algoStrong.map(c => (
                  <CandidateCard key={c.ticker} candidate={c} onClick={() => setCaseTicker(c.ticker)} />
                ))}
                {algoStrong.length > 0 && algoBuy.length > 0 && (
                  <div className="flex shrink-0 flex-col items-center justify-center px-1">
                    <div className="h-full w-px bg-border" />
                    <span className="num my-2 -rotate-90 whitespace-nowrap text-[9px] tracking-widest text-faint">
                      MODERATE
                    </span>
                    <div className="h-full w-px bg-border" />
                  </div>
                )}
                {algoBuy.map(c => (
                  <CandidateCard key={c.ticker} candidate={c} onClick={() => setCaseTicker(c.ticker)} />
                ))}
              </div>
            </div>
          </div>
        )}

        {/* ── STRONG BUY ── */}
        <div>
          <SectionHeader
            icon={IconStrongBuy}
            label="STRONG BUY"
            sub="Your hand-authored theses, conviction ≥ 4"
            count={strongBuy.length}
            tone="strong-buy"
          />
          {strongBuy.length === 0 ? (
            <div className="flex items-center gap-3 px-5 py-5">
              <span className="num text-[11px] text-faint">
                No strong buys — theses with conviction ≥ 4 will appear here
              </span>
            </div>
          ) : (
            <div className="overflow-x-auto border-b border-border">
              <div className="flex gap-3 p-4">
                {strongBuy.map(t => (
                  <SignalCard key={t.id} thesis={t} onClick={() => setModal(t)} />
                ))}
              </div>
            </div>
          )}
        </div>

        {/* ── WATCH ── */}
        {watch.length > 0 && (
          <div>
            <SectionHeader
              icon={IconWatch}
              label="WATCH"
              sub="Conviction 3 — thesis solid, waiting for entry signal"
              count={watch.length}
              tone="watch"
            />
            <div className="border-b border-border">
              <ThesisTable theses={watch} onRowClick={t => setModal(t)} />
            </div>
          </div>
        )}

        {/* ── MONITORING ── */}
        {monitoring.length > 0 && (
          <div>
            <SectionHeader
              icon={IconMonitor}
              label="MONITORING"
              sub="Active position — thesis not yet fully scored"
              count={monitoring.length}
              tone="monitor"
            />
            <div className="border-b border-border">
              <ThesisTable theses={monitoring} onRowClick={t => setModal(t)} />
            </div>
          </div>
        )}

        {/* ── RECENT CLOSES ── */}
        {closed.length > 0 && (
          <div>
            <SectionHeader
              icon={IconReview}
              label="RECENT CLOSES"
              count={closed.length}
              tone="default"
            />
            <div className="border-b border-border">
              <ThesisTable theses={closed.slice(0, 6)} dim onRowClick={t => setModal(t)} />
            </div>
          </div>
        )}

        {/* ── SMART MONEY (13F) ── */}
        <SmartMoneySection />

        {/* ── CONGRESS ── */}
        <CongressSection />

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
