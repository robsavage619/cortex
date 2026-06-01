import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { ChevronRight, Clock, ExternalLink, Megaphone, RefreshCw } from 'lucide-react'

import { Sparkline } from '@/components/charts/Sparkline'
import {
  useCalibration,
  useCandidates,
  useCongress,
  useCongressStats,
  useExecutive,
  useFunds,
  useHistory,
  useFreshness,
  useRefresh,
  useRefreshStatus,
  useReviewQueue,
  useTheses,
  useTickerContext,
} from '@/lib/api'
import type { Candidate, ExecutiveMention, Thesis } from '@/lib/types'
import { FACTORS, plainSection, zPercentileLabel, zPhrase } from '@/lib/plain'
import { usePlainMode } from '@/lib/plainMode'
import { TickerLogo } from '@/components/ui/TickerLogo'
import { StockModal } from '@/views/StockModal'
import { cn, daysUntil, fmtDate, fmtPrice, fmtSignedPercent } from '@/lib/utils'

// ── Bucket SVG icons ───────────────────────────────────────────────────────────


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

// ── Shared primitives ──────────────────────────────────────────────────────────

const STATUS_DOT: Record<string, string> = {
  open: 'bg-open',
  pending: 'bg-warn',
  confirmed: 'bg-up',
  invalidated: 'bg-down',
  closed: 'bg-muted',
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
  const { plain } = usePlainMode()
  return (
    <div className="flex shrink-0 items-center gap-2.5 border-b border-border bg-bg-panel px-5 py-2">
      <Icon className={cn('h-3.5 w-3.5', text)} />
      <span className={cn('label', text)}>{plain ? plainSection(label) : label}</span>
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
  const { plain } = usePlainMode()
  const term = FACTORS[label]
  const tooltip = term?.tip ?? label
  const shownLabel = plain ? (term?.plain ?? label) : label
  const labelWidth = plain ? 'w-[68px]' : 'w-9'
  if (z === null) {
    return (
      <div className="flex items-center gap-2">
        <span className={cn(labelWidth, 'font-sans text-[10px] text-muted')} title={tooltip}>{shownLabel}</span>
        <span className="num text-[10px] text-muted">{plain ? zPhrase(null) : '—'}</span>
      </div>
    )
  }
  const clamped = Math.max(-3, Math.min(3, z))
  const pct = ((clamped + 3) / 6) * 100
  const fill = z >= 0.5 ? 'bg-up' : z >= -0.5 ? 'bg-warn' : 'bg-down'
  const valueColor = z >= 0.5 ? 'text-up' : z >= -0.5 ? 'text-warn' : 'text-down'
  return (
    <div className="flex items-center gap-2" title={tooltip}>
      <span className={cn(labelWidth, 'font-sans text-[10px] text-muted')}>{shownLabel}</span>
      <div className="relative h-1.5 w-16 rounded-sm bg-border-bright">
        <div
          className={cn('absolute inset-y-0 left-0 rounded-sm', fill)}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className={cn('text-[10px] font-medium', plain ? 'font-sans' : 'num', valueColor)}>
        {plain ? zPhrase(z) : `${z >= 0 ? '+' : ''}${z.toFixed(2)}`}
      </span>
    </div>
  )
}

// ── Candidate card (DISCOVERED section) ───────────────────────────────────────

function CandidateCard({ candidate, onClick }: { candidate: Candidate; onClick: () => void }) {
  const { plain } = usePlainMode()
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
        <span
          className={cn('inline-flex items-center rounded-sm border px-1.5 py-0.5 text-[10px] font-bold', plain ? 'font-sans' : 'num tabular-nums', scoreColor)}
          title="Overall rank across all 5 factors vs. the S&P 500. Shown as a z-score (standard deviations); +2σ ≈ the top 2% of stocks."
        >
          {plain
            ? zPercentileLabel(candidate.composite_score)
            : `${candidate.composite_score >= 0 ? '+' : ''}${candidate.composite_score.toFixed(2)}z`}
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

// ── Executive-mention card (WHITE HOUSE BUZZ section) ─────────────────────────

const _SIG_STYLE: Record<string, string> = {
  high: 'border-cyan/40 bg-cyan/10 text-cyan',
  medium: 'border-warn/40 bg-warn/10 text-warn',
  low: 'border-border bg-border/30 text-faint',
}

function reactionOf(m: ExecutiveMention): { pct: number; label: string } | null {
  if (m.abn_5d != null) return { pct: m.abn_5d, label: '5d' }
  if (m.abn_1d != null) return { pct: m.abn_1d, label: '1d' }
  if (m.abn_20d != null) return { pct: m.abn_20d, label: '20d' }
  return null
}

function ExecutiveMentionRow({
  mention,
  onClick,
}: {
  mention: ExecutiveMention
  onClick: () => void
}) {
  const { plain } = usePlainMode()
  const [y, mo, d] = mention.mention_date.split('-').map(Number)
  const dt = new Date(y, mo - 1, d)
  const month = dt.toLocaleDateString([], { month: 'short' }).toUpperCase()
  const day = dt.toLocaleDateString([], { day: 'numeric' })

  const reaction = reactionOf(mention)
  const rUp = (reaction?.pct ?? 0) >= 0
  const incidental = mention.meaningful === false
  const sig = mention.significance

  const host = (() => {
    if (!mention.source_url) return ''
    try {
      return new URL(mention.source_url).hostname.replace('www.', '')
    } catch {
      return ''
    }
  })()

  return (
    <div
      onClick={onClick}
      className={cn(
        'group flex w-full cursor-pointer items-center gap-4 border-b border-border-dim px-5 py-4 transition-colors hover:bg-bg-hover',
        incidental && 'opacity-50',
      )}
    >
      {/* Date rail */}
      <div className="flex w-12 shrink-0 flex-col items-center">
        <span className="num text-[9px] font-semibold tracking-wider text-faint">{month}</span>
        <span className="num text-xl font-bold leading-none text-ink">{day}</span>
      </div>

      {/* Logo + ticker */}
      <div className="flex w-[92px] shrink-0 items-center gap-2.5">
        <TickerLogo ticker={mention.ticker} size={30} className="shrink-0" />
        <span className="num text-base font-bold text-ink">{mention.ticker}</span>
      </div>

      {/* Quote + meta */}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          {sig && (
            <span
              className={cn(
                'num rounded-sm border px-1.5 py-px text-[9px] font-semibold uppercase tracking-wide',
                _SIG_STYLE[sig] ?? _SIG_STYLE.low,
              )}
            >
              {plain ? `${sig} impact` : `${sig} sig`}
            </span>
          )}
          {incidental && (
            <span className="num text-[9px] uppercase tracking-wide text-faint">
              incidental
            </span>
          )}
          {mention.analysis && (
            <span className="font-sans text-[11px] italic text-faint">
              {mention.analysis}
            </span>
          )}
        </div>
        {mention.quote && (
          <p className="mt-1 line-clamp-2 font-sans text-[12.5px] leading-relaxed text-muted">
            “{mention.quote}”
          </p>
        )}
        {host && (
          <a
            href={mention.source_url ?? '#'}
            target="_blank"
            rel="noopener noreferrer"
            onClick={e => e.stopPropagation()}
            className="num mt-1.5 inline-flex items-center gap-1 text-[10px] text-faint transition-colors hover:text-cyan"
          >
            <ExternalLink className="h-2.5 w-2.5" />
            {host}
          </a>
        )}
      </div>

      {/* Reaction */}
      <div className="flex w-[104px] shrink-0 flex-col items-end">
        {reaction ? (
          <>
            <span
              className={cn(
                'num rounded-sm px-2 py-0.5 text-base font-bold',
                rUp ? 'bg-up/10 text-up' : 'bg-down/10 text-down',
              )}
            >
              {rUp ? '+' : ''}{(reaction.pct * 100).toFixed(1)}%
            </span>
            <span className="num mt-1 text-[9px] text-faint">
              {plain ? `${reaction.label} after mention` : `${reaction.label} vs SPY`}
            </span>
          </>
        ) : (
          <span className="num text-[10px] text-faint">too recent</span>
        )}
      </div>
    </div>
  )
}

// ── Sync-all-data button ───────────────────────────────────────────────────────

const _LS_KEY = 'cortex:lastSynced'

function SyncButton() {
  const qc = useQueryClient()
  const refresh = useRefresh()
  const candidates = useCandidates()
  const [polling, setPolling] = useState(false)
  const [lastSynced, setLastSyncedState] = useState<string | null>(
    () => localStorage.getItem(_LS_KEY),
  )
  const status = useRefreshStatus(polling)
  const running = polling && (status.data?.running ?? true)

  // Seed from DB-persisted last_run if localStorage is empty
  useEffect(() => {
    if (!lastSynced && candidates.data?.last_run) {
      const t = new Date(candidates.data.last_run)
      const label = t.toLocaleDateString([], { month: 'short', day: 'numeric' }) +
        ' ' + t.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      setLastSyncedState(label)
    }
  }, [candidates.data?.last_run, lastSynced])

  const setLastSynced = (val: string) => {
    localStorage.setItem(_LS_KEY, val)
    setLastSyncedState(val)
  }

  useEffect(() => {
    if (polling && status.data && !status.data.running) {
      void qc.invalidateQueries({ queryKey: ['candidates'] })
      void qc.invalidateQueries({ queryKey: ['congress'] })
      void qc.invalidateQueries({ queryKey: ['funds'] })
      void qc.invalidateQueries({ queryKey: ['theses'] })
      void qc.invalidateQueries({ queryKey: ['ticker-context'] })
      setPolling(false)
      if (status.data.finished_at) {
        const t = new Date(status.data.finished_at)
        setLastSynced(t.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }))
      }
    }
  }, [status.data, polling, qc])

  const steps = status.data?.steps ?? {}
  const activeStep =
    steps.discover === 'running' ? 'scanning S&P 500…'
    : steps.congress === 'running' ? 'syncing congress…'
    : 'starting…'

  return (
    <div className="flex items-center gap-2">
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
      {lastSynced && !running && (
        <span className="num text-[10px] text-faint">synced {lastSynced}</span>
      )}
    </div>
  )
}

// ── Per-source freshness strip ───────────────────────────────────────────────

const _STALE_AFTER: Record<string, number> = {
  // seconds past which a source is considered stale, per expected cadence
  congress: 36 * 3600, // daily cron + slack
  discover: 36 * 3600,
  volatility: 36 * 3600,
  funds: 10 * 24 * 3600, // weekly cron + slack
}

function fmtAge(seconds: number | null): string {
  if (seconds == null) return '—'
  const h = seconds / 3600
  if (h < 1) return `${Math.max(1, Math.round(seconds / 60))}m`
  if (h < 48) return `${Math.round(h)}h`
  return `${Math.round(h / 24)}d`
}

function FreshnessStrip() {
  const { data } = useFreshness()
  if (!data || data.length === 0) return null

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      {data.map(s => {
        const stale =
          s.age_seconds != null && s.age_seconds > (_STALE_AFTER[s.source] ?? 36 * 3600)
        const tone = !s.ok ? 'bg-down' : stale ? 'bg-warn' : 'bg-cyan'
        const title = !s.ok
          ? `last run failed: ${s.detail ?? 'unknown error'}` +
            (s.last_ok_at ? ` — last ok ${new Date(s.last_ok_at).toLocaleString()}` : '')
          : `${s.detail ?? 'ok'} — ${new Date(s.last_run_at ?? '').toLocaleString()}`
        return (
          <span
            key={s.source}
            title={title}
            className="num flex items-center gap-1 text-[10px] text-faint"
          >
            <span className={cn('h-1.5 w-1.5 rounded-full', tone)} />
            {s.source} {fmtAge(s.age_seconds)}
          </span>
        )
      })}
    </div>
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

function CongressHeatmap() {
  const { data } = useCongressStats(120)
  const top = (data?.top_tickers ?? []).slice(0, 8)
  if (top.length === 0) return null

  const maxNotional = Math.max(...top.map(t => Math.max(t.buy_notional, t.sell_notional)), 1)

  return (
    <div className="border-b border-border px-5 py-4" style={{ background: 'rgba(255,255,255,0.015)' }}>
      <span className="label mb-3 block text-[9px] tracking-[0.12em] text-muted/60">SENATE FLOW BY TICKER · 120D</span>
      <div className="space-y-2.5">
        {top.map(t => {
          const buyPct = (t.buy_notional / maxNotional) * 100
          const sellPct = (t.sell_notional / maxNotional) * 100
          const netBuy = t.buy_notional >= t.sell_notional
          return (
            <div key={t.ticker} className="grid items-center gap-3" style={{ gridTemplateColumns: '44px 1fr 52px' }}>
              <span className={cn('num text-[10px] font-bold tracking-wide', netBuy ? 'text-up' : 'text-down')}>
                {t.ticker}
              </span>
              <div className="space-y-[3px]">
                {/* Buy bar */}
                <div className="relative h-[5px] w-full overflow-hidden rounded-full" style={{ background: 'rgba(255,255,255,0.05)' }}>
                  <div
                    className="absolute inset-y-0 left-0 rounded-full transition-all duration-500"
                    style={{
                      width: `${buyPct}%`,
                      background: 'linear-gradient(90deg, rgba(52,211,153,0.7) 0%, rgba(52,211,153,0.25) 100%)',
                    }}
                  />
                  {buyPct > 2 && (
                    <div
                      className="absolute inset-y-0 w-[2px] rounded-full"
                      style={{
                        left: `calc(${buyPct}% - 1px)`,
                        background: 'rgba(52,211,153,0.9)',
                        boxShadow: '0 0 4px rgba(52,211,153,0.7)',
                      }}
                    />
                  )}
                </div>
                {/* Sell bar */}
                <div className="relative h-[5px] w-full overflow-hidden rounded-full" style={{ background: 'rgba(255,255,255,0.05)' }}>
                  <div
                    className="absolute inset-y-0 left-0 rounded-full transition-all duration-500"
                    style={{
                      width: `${sellPct}%`,
                      background: 'linear-gradient(90deg, rgba(248,113,113,0.65) 0%, rgba(248,113,113,0.2) 100%)',
                    }}
                  />
                  {sellPct > 2 && (
                    <div
                      className="absolute inset-y-0 w-[2px] rounded-full"
                      style={{
                        left: `calc(${sellPct}% - 1px)`,
                        background: 'rgba(248,113,113,0.85)',
                        boxShadow: '0 0 4px rgba(248,113,113,0.6)',
                      }}
                    />
                  )}
                </div>
              </div>
              <div className="flex shrink-0 justify-end gap-2">
                {t.buyers > 0 && <span className="num text-[9px] text-up/70">{t.buyers}B</span>}
                {t.sellers > 0 && <span className="num text-[9px] text-down/60">{t.sellers}S</span>}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
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
      {trades.length > 0 && <CongressHeatmap />}
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

function SmartMoneyConviction({ moves }: { moves: { manager: string; ticker: string; action: string; value: number }[] }) {
  type Agg = { managers: Set<string>; value: number; hasNew: boolean }
  const byTicker = new Map<string, Agg>()
  for (const m of moves) {
    const agg = byTicker.get(m.ticker) ?? { managers: new Set(), value: 0, hasNew: false }
    agg.managers.add(m.manager)
    agg.value += m.value
    if (m.action === 'NEW') agg.hasNew = true
    byTicker.set(m.ticker, agg)
  }
  const sorted = [...byTicker.entries()]
    .map(([ticker, agg]) => ({ ticker, count: agg.managers.size, value: agg.value, hasNew: agg.hasNew }))
    .sort((a, b) => b.count - a.count || b.value - a.value)
    .slice(0, 8)

  if (sorted.length === 0) return null
  const maxCount = Math.max(...sorted.map(r => r.count), 1)

  return (
    <div className="border-b border-border px-5 py-4" style={{ background: 'rgba(255,255,255,0.015)' }}>
      <span className="label mb-3 block text-[9px] tracking-[0.12em] text-muted/60">INSTITUTIONAL CONVICTION · MANAGERS BUYING</span>
      <div className="space-y-2.5">
        {sorted.map(row => {
          const pct = (row.count / maxCount) * 100
          return (
            <div key={row.ticker} className="grid items-center gap-3" style={{ gridTemplateColumns: '44px 1fr 110px' }}>
              <span className="num text-[10px] font-bold tracking-wide text-cyan">{row.ticker}</span>
              <div className="relative h-[5px] overflow-hidden rounded-full" style={{ background: 'rgba(255,255,255,0.05)' }}>
                <div
                  className="absolute inset-y-0 left-0 rounded-full transition-all duration-500"
                  style={{
                    width: `${pct}%`,
                    background: 'linear-gradient(90deg, rgba(6,182,212,0.65) 0%, rgba(6,182,212,0.2) 100%)',
                  }}
                />
                {pct > 2 && (
                  <div
                    className="absolute inset-y-0 w-[2px] rounded-full"
                    style={{
                      left: `calc(${pct}% - 1px)`,
                      background: 'rgba(6,182,212,0.9)',
                      boxShadow: '0 0 5px rgba(6,182,212,0.7)',
                    }}
                  />
                )}
              </div>
              <div className="flex items-center justify-end gap-2">
                <span className="num text-[9px] text-muted">{row.count} {row.count === 1 ? 'mgr' : 'mgrs'}</span>
                <span className="num text-[9px] text-faint">{fmtBigUsd(row.value)}</span>
                {row.hasNew && (
                  <span className="num rounded-sm border border-up/30 bg-up/10 px-1 py-px text-[7px] font-bold tracking-widest text-up">NEW</span>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
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
      {moves.length > 0 && <SmartMoneyConviction moves={moves} />}
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
  const executive = useExecutive()
  const [modal, setModal] = useState<Thesis | null>(null)
  const [caseTicker, setCaseTicker] = useState<string | null>(null)

  const mentions = executive.data?.mentions ?? []

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

      {/* Per-source data freshness */}
      <div className="shrink-0 border-b border-line/40 px-5 py-1.5">
        <FreshnessStrip />
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

        {/* ── EXECUTIVE MENTIONS (WHITE HOUSE BUZZ) ── */}
        {mentions.length > 0 && (
          <div>
            <SectionHeader
              icon={Megaphone}
              label="EXECUTIVE MENTIONS"
              sub="companies the White House named in statements, fact-sheets & remarks — and how the stock moved after"
              count={mentions.length}
              tone="watch"
            />
            <div className="border-b border-border">
              {mentions.map((m, i) => (
                <ExecutiveMentionRow
                  key={`${m.ticker}-${m.mention_date}-${i}`}
                  mention={m}
                  onClick={() => setCaseTicker(m.ticker)}
                />
              ))}
            </div>
          </div>
        )}

        {/* ── DISCOVERED ── */}
        <div>
          <SectionHeader
            icon={IconDiscovered}
            label="DISCOVERED"
            sub={lastRun ? `full S&P 500 ranked by composite score · last run ${new Date(lastRun).toLocaleDateString()}` : 'run cortex discover to populate'}
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
              sub="stocks scoring ≥+0.2σ composite — a subset of DISCOVERED that clears the algorithm's buy threshold"
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
