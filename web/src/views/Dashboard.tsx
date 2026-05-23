import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ChevronRight, TrendingDown, TrendingUp } from 'lucide-react'

import { PriceChart } from '@/components/charts/PriceChart'
import { Sparkline } from '@/components/charts/Sparkline'
import { useCalibration, useHistory, useReviewQueue, useTheses, useTickerContext } from '@/lib/api'
import type { Thesis, ThesisStatus } from '@/lib/types'
import { cn, daysUntil, fmtDate, fmtPrice, fmtSignedPercent } from '@/lib/utils'

// ── Live price cell ───────────────────────────────────────────────────────────

function LivePrice({ ticker, entryPrice }: { ticker: string; entryPrice: number | null }) {
  const { data, isLoading } = useTickerContext(ticker)
  const price  = data?.market?.price ?? null
  const change = data?.market?.day_change_percent ?? null
  const up     = (change ?? 0) >= 0

  const prevRef = useRef<number | null>(null)
  const spanRef = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    if (price == null || prevRef.current == null) { prevRef.current = price; return }
    if (price === prevRef.current) return
    const cls = price > prevRef.current ? 'flash-up' : 'flash-down'
    spanRef.current?.classList.remove('flash-up', 'flash-down')
    void spanRef.current?.offsetWidth
    spanRef.current?.classList.add(cls)
    prevRef.current = price
  }, [price])

  if (isLoading) return <span className="num text-[11px] text-faint">…</span>
  if (!price)    return <span className="num text-[11px] text-faint">—</span>

  const pnl   = entryPrice != null ? ((price - entryPrice) / entryPrice) * 100 : null
  const pnlUp = (pnl ?? 0) >= 0

  return (
    <div className="flex flex-col gap-px">
      <span ref={spanRef} className={cn('num text-[12px] font-semibold', up ? 'text-up' : 'text-down')}>
        {fmtPrice(price)}{' '}
        <span className="font-normal">
          {up ? <TrendingUp className="inline h-2.5 w-2.5" /> : <TrendingDown className="inline h-2.5 w-2.5" />}
          {' '}{fmtSignedPercent(change)}
        </span>
      </span>
      {pnl != null && (
        <span className={cn('num text-[10px]', pnlUp ? 'text-up' : 'text-down')}>
          vs entry {pnlUp ? '+' : ''}{pnl.toFixed(1)}%
        </span>
      )}
    </div>
  )
}

// ── Inline sparkline ──────────────────────────────────────────────────────────

function RowSparkline({ ticker }: { ticker: string }) {
  const { data } = useHistory(ticker, '3mo')
  const closes = data?.map(b => b.close) ?? []
  if (closes.length < 4) return <span className="text-faint text-[11px]">…</span>
  return <Sparkline values={closes} width={64} height={20} />
}

// ── 3-block conviction ────────────────────────────────────────────────────────

function ConvBlocks({ value }: { value: number }) {
  const filled = value <= 2 ? 1 : value === 3 ? 2 : 3
  const tone   = value <= 2 ? 'bg-open/50' : value === 3 ? 'bg-warn' : 'bg-up'
  return (
    <span className="inline-flex items-center gap-px" title={`${value}/5`}>
      {Array.from({ length: 3 }, (_, i) => (
        <span key={i} className={cn('inline-block h-3 w-2', i < filled ? tone : 'bg-border')} />
      ))}
    </span>
  )
}

// ── Status ────────────────────────────────────────────────────────────────────

const DOT: Record<string, string> = {
  open:'bg-open', pending:'bg-warn', confirmed:'bg-up', invalidated:'bg-down', closed:'bg-muted'
}
const STATUS_TEXT: Record<string, string> = {
  open:'text-open', pending:'text-warn', confirmed:'text-up', invalidated:'text-down', closed:'text-muted'
}

// ── Sort ──────────────────────────────────────────────────────────────────────

type SortKey = 'review_date' | 'conviction' | 'status' | 'tickers'
type SortDir = 'asc' | 'desc'

function applySortAndFilter(
  rows: Thesis[], key: SortKey, dir: SortDir, filter: ThesisStatus | 'all'
) {
  const filtered = filter === 'all' ? rows : rows.filter(t => t.status === filter)
  return [...filtered].sort((a, b) => {
    let c = 0
    if (key === 'conviction')  c = a.conviction - b.conviction
    if (key === 'review_date') c = a.review_date.localeCompare(b.review_date)
    if (key === 'status')      c = a.status.localeCompare(b.status)
    if (key === 'tickers')     c = (a.tickers[0] ?? '').localeCompare(b.tickers[0] ?? '')
    return dir === 'asc' ? c : -c
  })
}

function ColHead({ label, k, cur, dir, onSort, className }: {
  label: string; k?: SortKey; cur: SortKey; dir: SortDir
  onSort: (k: SortKey) => void; className?: string
}) {
  const active = k === cur
  return (
    <th
      onClick={k ? () => onSort(k) : undefined}
      className={cn('label border-b border-border px-3 py-2 text-left',
        k && 'cursor-pointer select-none hover:text-ink', active && 'text-cyan', className)}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        <span className="w-2.5">{active ? (dir === 'asc' ? '↑' : '↓') : ''}</span>
      </span>
    </th>
  )
}

// ── Thesis row ────────────────────────────────────────────────────────────────

function Row({ t, even, selected, onSelect }: {
  t: Thesis; even: boolean; selected: boolean; onSelect: () => void
}) {
  const days    = daysUntil(t.review_date)
  const overdue = days < 0
  const soon    = days >= 0 && days <= 7
  const lead    = t.tickers[0] ?? null

  return (
    <tr
      onClick={onSelect}
      className={cn(
        'group cursor-pointer border-b border-border-dim transition-colors',
        selected
          ? 'bg-bg-selected'
          : even ? 'bg-bg-row hover:bg-bg-hover' : 'bg-bg-row-alt hover:bg-bg-hover',
        (t.status === 'invalidated' || t.status === 'closed') && 'opacity-50',
      )}
    >
      <td className="w-5 px-2 py-1.5 text-center">
        <span className={cn('inline-block h-1.5 w-1.5 rounded-full', DOT[t.status] ?? 'bg-muted')} />
      </td>
      <td className="w-[80px] px-3 py-1.5">
        <span className="num text-[12px] font-bold text-ink">{t.tickers.slice(0, 2).join(' ')}</span>
      </td>
      <td className="px-3 py-1.5 max-w-0">
        <span className="block truncate text-[13px] text-ink font-sans">{t.claim}</span>
        <span className="block truncate text-[11px] text-muted font-sans">⚡ {t.falsifier}</span>
      </td>
      <td className="w-14 px-2 py-1.5">
        <ConvBlocks value={t.conviction} />
      </td>
      <td className="w-24 px-3 py-1.5">
        <span className={cn('num text-[11px] font-semibold', STATUS_TEXT[t.status] ?? 'text-muted')}>
          {t.status.toUpperCase()}
        </span>
      </td>
      <td className="w-20 px-3 py-1.5">
        {lead ? <RowSparkline ticker={lead} /> : <span className="text-faint">—</span>}
      </td>
      <td className="w-[150px] px-3 py-1.5">
        {lead ? <LivePrice ticker={lead} entryPrice={t.entry_price} /> : <span className="num text-[11px] text-faint">—</span>}
      </td>
      <td className="w-28 px-3 py-1.5">
        <span className="num block text-[11px] text-muted">{fmtDate(t.review_date)}</span>
        <span className={cn('num block text-[10px] font-semibold',
          overdue ? 'text-down' : soon ? 'text-warn' : 'text-faint')}>
          {overdue ? `${Math.abs(days)}d OVERDUE` : days === 0 ? 'TODAY' : `${days}d`}
        </span>
      </td>
      <td className="w-7 px-2 py-1.5">
        <ChevronRight className="h-3.5 w-3.5 text-faint opacity-0 group-hover:opacity-100 transition-opacity" />
      </td>
    </tr>
  )
}

// ── KPI tile ──────────────────────────────────────────────────────────────────

function Kpi({ label, value, sub, tone }: {
  label: string; value: string | number; sub?: string
  tone?: 'up' | 'down' | 'warn' | 'cyan' | 'open' | 'muted'
}) {
  const colors = { up:'text-up', down:'text-down', warn:'text-warn', cyan:'text-cyan', open:'text-open', muted:'text-muted' }
  return (
    <div className="flex flex-col gap-0.5 border-r border-border px-4 py-2.5 last:border-r-0">
      <span className="label">{label}</span>
      <span className={cn('num text-2xl font-semibold leading-none', colors[tone ?? 'muted'])}>{value}</span>
      {sub && <span className="num mt-0.5 text-[10px] text-faint">{sub}</span>}
    </div>
  )
}

// ── Right panel: chart + thesis detail ───────────────────────────────────────

function DetailPanel({ thesis }: { thesis: Thesis }) {
  const lead       = thesis.tickers[0] ?? ''
  const { data }   = useTickerContext(lead)
  const { data: bars } = useHistory(lead, '6mo')
  const price      = data?.market?.price ?? null
  const change   = data?.market?.day_change_percent ?? null
  const up       = (change ?? 0) >= 0
  const days     = daysUntil(thesis.review_date)
  const overdue  = days < 0

  return (
    <div className="flex h-full flex-col border-l border-border bg-bg-panel">
      {/* Panel header */}
      <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
        <div className="flex items-center gap-2">
          <span className="num text-lg font-bold text-ink">{lead}</span>
          {price != null && (
            <span className={cn('num text-sm', up ? 'text-up' : 'text-down')}>
              {fmtPrice(price)} {fmtSignedPercent(change)}
            </span>
          )}
        </div>
        <Link
          to={`/thesis/${thesis.id}`}
          className="num text-[10px] tracking-widest text-muted hover:text-cyan"
        >
          OPEN FULL →
        </Link>
      </div>

      {/* Price chart */}
      <div className="border-b border-border">
        <PriceChart
          bars={bars ?? []}
          entryPrice={thesis.entry_price}
          height={200}
        />
      </div>

      {/* Thesis metadata */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">

        {/* Status + conviction */}
        <div className="flex items-center gap-3">
          <span className={cn('num text-xs font-semibold tracking-widest', STATUS_TEXT[thesis.status] ?? 'text-muted')}>
            {thesis.status.toUpperCase()}
          </span>
          <span className="text-border">|</span>
          <ConvBlocks value={thesis.conviction} />
          <span className="num text-[11px] text-faint">{thesis.conviction}/5 conviction</span>
        </div>

        {/* Claim */}
        <div>
          <span className="label block mb-1">THESIS</span>
          <p className="font-sans text-[12px] text-ink leading-relaxed">{thesis.claim}</p>
        </div>

        {/* Falsifier */}
        <div>
          <span className="label block mb-1">INVALIDATED IF</span>
          <p className="font-sans text-[12px] text-muted leading-relaxed">⚡ {thesis.falsifier}</p>
        </div>

        {/* Review date */}
        <div className="flex items-center justify-between border-t border-border pt-3">
          <span className="label">REVIEW DATE</span>
          <div className="text-right">
            <span className="num block text-[12px] text-ink">{fmtDate(thesis.review_date)}</span>
            <span className={cn('num text-[10px]', overdue ? 'text-down' : days <= 7 ? 'text-warn' : 'text-faint')}>
              {overdue ? `${Math.abs(days)}d overdue` : `${days}d remaining`}
            </span>
          </div>
        </div>

        {/* Entry */}
        {thesis.entry_price != null && (
          <div className="flex items-center justify-between border-t border-border pt-3">
            <span className="label">ENTRY PRICE</span>
            <span className="num text-[12px] text-ink">{fmtPrice(thesis.entry_price)}</span>
          </div>
        )}

        {/* Author */}
        <div className="flex items-center justify-between border-t border-border pt-3">
          <span className="label">AUTHOR</span>
          <span className="num text-[12px] text-muted">{thesis.author.toUpperCase()}</span>
        </div>

        {/* Market context */}
        {data?.market && (
          <div className="border-t border-border pt-3 space-y-2">
            <span className="label block">MARKET CONTEXT</span>
            <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
              {data.market.pe_ratio != null && (
                <>
                  <span className="label text-faint">P/E</span>
                  <span className="num text-[11px] text-muted text-right">{data.market.pe_ratio.toFixed(1)}×</span>
                </>
              )}
              {data.market.week_52_high != null && (
                <>
                  <span className="label text-faint">52W HIGH</span>
                  <span className="num text-[11px] text-muted text-right">{fmtPrice(data.market.week_52_high)}</span>
                </>
              )}
              {data.market.week_52_low != null && (
                <>
                  <span className="label text-faint">52W LOW</span>
                  <span className="num text-[11px] text-muted text-right">{fmtPrice(data.market.week_52_low)}</span>
                </>
              )}
              {data.market.market_cap != null && (
                <>
                  <span className="label text-faint">MKTCAP</span>
                  <span className="num text-[11px] text-muted text-right">
                    ${(data.market.market_cap / 1e9).toFixed(0)}B
                  </span>
                </>
              )}
            </div>
          </div>
        )}

        {/* Recent news headlines */}
        {data?.market?.news_headlines && data.market.news_headlines.length > 0 && (
          <div className="border-t border-border pt-3 space-y-1.5">
            <span className="label block">RECENT NEWS</span>
            {data.market.news_headlines.slice(0, 4).map((h, i) => (
              <p key={i} className="font-sans text-[11px] text-muted leading-snug">• {h}</p>
            ))}
          </div>
        )}

      </div>

      {/* Footer action */}
      <div className="border-t border-border p-3">
        <Link
          to={`/thesis/${thesis.id}`}
          className="num flex w-full items-center justify-center gap-2 border border-cyan py-1.5 text-[11px] font-semibold tracking-widest text-cyan transition-colors hover:bg-cyan hover:text-bg"
        >
          OPEN / REVIEW THESIS →
        </Link>
      </div>
    </div>
  )
}

// ── Dashboard ─────────────────────────────────────────────────────────────────

const FILTERS: { label: string; value: ThesisStatus | 'all' }[] = [
  { label: 'ALL',         value: 'all'         },
  { label: 'OPEN',        value: 'open'        },
  { label: 'PENDING',     value: 'pending'     },
  { label: 'CONFIRMED',   value: 'confirmed'   },
  { label: 'INVALIDATED', value: 'invalidated' },
  { label: 'CLOSED',      value: 'closed'      },
]

export function Dashboard() {
  const theses = useTheses()
  const queue  = useReviewQueue()
  const cal    = useCalibration()

  const [sortKey,  setSortKey]  = useState<SortKey>('review_date')
  const [sortDir,  setSortDir]  = useState<SortDir>('asc')
  const [filter,   setFilter]   = useState<ThesisStatus | 'all'>('all')
  const [selected, setSelected] = useState<string | null>(null)

  const all    = theses.data ?? []
  const active = all.filter(t => t.status === 'open' || t.status === 'pending')
  const closed = all.filter(t => ['confirmed','invalidated','closed'].includes(t.status))
  const hits   = closed.filter(t => t.status === 'confirmed').length
  const hitRate = closed.length > 0 ? `${((hits / closed.length) * 100).toFixed(0)}%` : '—'
  const due    = queue.data?.length ?? 0

  const rows = useMemo(
    () => applySortAndFilter(all, sortKey, sortDir, filter),
    [all, sortKey, sortDir, filter],
  )

  const handleSort = (k: SortKey) => {
    if (k === sortKey) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortKey(k); setSortDir('asc') }
  }

  // Auto-select first row
  useEffect(() => {
    if (rows.length > 0 && selected === null) setSelected(rows[0].id)
  }, [rows, selected])

  const focusedThesis = all.find(t => t.id === selected) ?? null

  if (theses.isLoading) {
    return <div className="flex flex-1 items-center justify-center">
      <span className="num text-sm text-muted">LOADING…</span>
    </div>
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">

      {/* ── KPI bar ───────────────────────────────────────── */}
      <div className="flex shrink-0 items-stretch border-b border-border bg-bg-panel">
        <Kpi label="ACTIVE"   value={active.length} tone="open" />
        <Kpi label="DUE"      value={due}
             sub={due > 0 ? 'ACTION NEEDED' : 'ALL CLEAR'}
             tone={due > 0 ? 'warn' : 'muted'} />
        <Kpi label="HIT RATE" value={hitRate}
             sub={closed.length > 0 ? `${closed.length} REVIEWED` : 'NO REVIEWS YET'}
             tone={hits > 0 ? 'up' : 'muted'} />
        <Kpi label="BRIER"
             value={cal.data ? cal.data.brier_score.toFixed(3) : '—'}
             sub={cal.data?.overconfident ? 'OVERCONFIDENT' : cal.data ? 'CALIBRATED' : 'NEEDS DATA'}
             tone={cal.data?.overconfident ? 'warn' : 'muted'} />
        <Kpi label="TOTAL" value={all.length} tone="muted" />
        <div className="ml-auto flex items-center px-4">
          <Link to="/new" className="num border border-cyan px-3 py-1.5 text-[11px] font-semibold tracking-widest text-cyan hover:bg-cyan hover:text-bg transition-colors">
            + NEW THESIS
          </Link>
        </div>
      </div>

      {/* ── Filter bar ────────────────────────────────────── */}
      <div className="flex shrink-0 items-center gap-px border-b border-border bg-bg-panel px-3">
        {FILTERS.map(f => {
          const count = f.value === 'all' ? all.length : all.filter(t => t.status === f.value).length
          return (
            <button key={f.value} onClick={() => setFilter(f.value)}
              className={cn('num px-3 py-1.5 text-[10px] font-semibold tracking-widest transition-colors',
                filter === f.value ? 'border-b-2 border-cyan text-cyan' : 'text-muted hover:text-ink')}>
              {f.label}{count > 0 && <span className="ml-1 text-faint">({count})</span>}
            </button>
          )
        })}
      </div>

      {/* ── Split: table left + detail right ──────────────── */}
      <div className="flex flex-1 overflow-hidden">

        {/* Left: table */}
        <div className="flex-1 overflow-auto min-w-0">
          {rows.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-3 py-24">
              <span className="num text-sm text-muted">
                {all.length === 0 ? 'NO THESES' : `NO ${filter.toUpperCase()} THESES`}
              </span>
              {all.length === 0 && (
                <Link to="/new" className="num mt-1 border border-cyan px-4 py-1.5 text-[11px] font-semibold tracking-widest text-cyan hover:bg-cyan hover:text-bg">
                  CREATE FIRST THESIS
                </Link>
              )}
            </div>
          ) : (
            <table className="w-full">
              <colgroup>
                <col className="w-5" />
                <col className="w-[80px]" />
                <col />
                <col className="w-14" />
                <col className="w-24" />
                <col className="w-20" />
                <col className="w-[150px]" />
                <col className="w-28" />
                <col className="w-7" />
              </colgroup>
              <thead className="sticky top-0 z-10 bg-bg-panel">
                <tr>
                  <th className="w-5 border-b border-border" />
                  <ColHead label="TICKER"  k="tickers"     cur={sortKey} dir={sortDir} onSort={handleSort} />
                  <ColHead label="THESIS"                  cur={sortKey} dir={sortDir} onSort={handleSort} />
                  <ColHead label="CONV"    k="conviction"  cur={sortKey} dir={sortDir} onSort={handleSort} />
                  <ColHead label="STATUS"  k="status"      cur={sortKey} dir={sortDir} onSort={handleSort} />
                  <th className="label w-20 border-b border-border px-3 py-2 text-left">TREND</th>
                  <th className="label w-[150px] border-b border-border px-3 py-2 text-left">PRICE</th>
                  <ColHead label="REVIEW"  k="review_date" cur={sortKey} dir={sortDir} onSort={handleSort} />
                  <th className="w-7 border-b border-border" />
                </tr>
              </thead>
              <tbody>
                {rows.map((t, i) => (
                  <Row key={t.id} t={t} even={i % 2 === 0}
                    selected={selected === t.id} onSelect={() => setSelected(t.id)} />
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Right: detail panel (fixed 320px) */}
        {focusedThesis && (
          <div className="w-[320px] shrink-0 overflow-hidden">
            <DetailPanel thesis={focusedThesis} />
          </div>
        )}

      </div>
    </div>
  )
}
