import { Fragment, useMemo, useState } from 'react'
import {
  Cell,
  LabelList,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from 'recharts'
import { ChevronDown, ChevronRight, Fish, HelpCircle, X } from 'lucide-react'

import { useFunds } from '@/lib/api'
import type { FundMove } from '@/lib/types'
import { TickerLogo } from '@/components/ui/TickerLogo'
import { TradeImpactChart } from '@/components/charts/TradeImpactChart'
import { StockModal } from '@/views/StockModal'
import { cn, fmtCompact, fmtDate } from '@/lib/utils'

const fmtUsd = (v: number | null | undefined): string =>
  v == null || Number.isNaN(v) ? '—' : `$${fmtCompact(v)}`

/**
 * Resolve a filing's `period` to an ISO date for pricing the chart. The backend
 * sends the 13F filing date (YYYY-MM-DD); older shapes used "Q1 2024".
 */
function filingDate(period: string | null): string | null {
  if (!period) return null
  if (/^\d{4}-\d{2}-\d{2}$/.test(period)) return period
  const m = /Q([1-4])\s+(\d{4})/.exec(period)
  if (!m) return null
  const ends: Record<string, string> = { '1': '03-31', '2': '06-30', '3': '09-30', '4': '12-31' }
  return `${m[2]}-${ends[m[1]]}`
}

// ── KPI tile (matches Congress / SwingScreen) ──────────────────────────────────

function Kpi({ label, value, sub, tone }: {
  label: string; value: string | number; sub?: string
  tone?: 'up' | 'down' | 'warn' | 'muted' | 'cyan'
}) {
  const colors = { up: 'text-up', down: 'text-down', warn: 'text-warn', muted: 'text-muted', cyan: 'text-cyan' }
  return (
    <div className="flex flex-col gap-0.5 border-r border-border px-5 py-3 last:border-r-0">
      <span className="label">{label}</span>
      <span className={cn('num text-2xl font-semibold leading-none', colors[tone ?? 'muted'])}>{value}</span>
      {sub && <span className="num mt-0.5 text-[10px] text-faint">{sub}</span>}
    </div>
  )
}

// ── How-to / explainer panel ────────────────────────────────────────────────────

function HowToPanel() {
  const [open, setOpen] = useState(false)
  return (
    <div className="shrink-0 border-b border-border">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex w-full items-center gap-2 px-5 py-2 text-left transition-colors hover:bg-bg-hover"
      >
        <HelpCircle className="h-3.5 w-3.5 text-cyan" />
        <span className="num text-[11px] font-semibold tracking-[0.1em] text-cyan">WHAT IS THIS PAGE</span>
        {open ? <ChevronDown className="h-3.5 w-3.5 text-faint" /> : <ChevronRight className="h-3.5 w-3.5 text-faint" />}
        {!open && (
          <span className="font-sans text-[11px] text-faint">
            — the latest stock buys from <span className="text-muted">hedge funds, asset managers and other big institutions</span>, pulled straight from their SEC filings
          </span>
        )}
      </button>

      {open && (
        <div className="border-t border-border-dim bg-bg px-5 pb-5 pt-4">
          <div className="mb-4 grid gap-4 lg:grid-cols-3">
            <div className="border-l-2 border-cyan/30 pl-3">
              <div className="num mb-1 text-[11px] font-semibold text-cyan">Who these whales are</div>
              <p className="font-sans text-[11px] leading-snug text-faint">
                Any institution managing over <span className="text-muted">$100M</span> — hedge funds like
                Burry's Scion and Ackman's Pershing Square, asset managers like Cathie Wood's ARK, and
                conglomerates like Buffett's Berkshire — must file a <span className="text-muted">Form 13F</span>
                {' '}listing every U.S. stock they hold.
              </p>
            </div>
            <div className="border-l-2 border-up/30 pl-3">
              <div className="num mb-1 text-[11px] font-semibold text-up">NEW vs ADD</div>
              <p className="font-sans text-[11px] leading-snug text-faint">
                A <span className="text-up">NEW</span> position means the fund just opened a brand-new stake — its
                strongest signal of fresh conviction. An <span className="text-cyan">ADD</span> means it already
                owned the name and bought more. We only surface buying, never trims.
              </p>
            </div>
            <div className="border-l-2 border-warn/30 pl-3">
              <div className="num mb-1 text-[11px] font-semibold text-warn">Why it's always a little stale</div>
              <p className="font-sans text-[11px] leading-snug text-faint">
                13F filings are due <span className="text-muted">45 days</span> after each quarter ends, so you're
                seeing where the smart money was as of the quarter close — not necessarily where it is today.
                Expand any row to see how the stock has moved since.
              </p>
            </div>
          </div>
          <div className="border border-cyan/20 bg-cyan/5 px-4 py-3">
            <div className="num mb-1 text-[10px] font-semibold tracking-widest text-cyan">THE FUND-FLOW FACTOR</div>
            <p className="font-sans text-[12px] leading-relaxed text-muted max-w-3xl">
              CORTEX builds a signal from this data: when many tracked funds pile into the same name, that crowding
              is tested against forward returns. As of the last backtest it scores a{' '}
              <span className="text-ink font-medium">t-stat of 2.58</span> — the strongest of any single factor here,
              but still under the <span className="text-ink font-medium">t ≥ 3.0</span> pre-registration bar, so it
              guides research rather than live trades.
            </p>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Aggregations ─────────────────────────────────────────────────────────────────

interface TickerAgg { ticker: string; managers: number; value: number; count: number; hasNew: boolean }
interface ManagerAgg { manager: string; value: number; news: number; adds: number; count: number }

function aggTickers(moves: FundMove[]): TickerAgg[] {
  const map = new Map<string, { managers: Set<string>; value: number; count: number; hasNew: boolean }>()
  for (const m of moves) {
    const a = map.get(m.ticker) ?? { managers: new Set(), value: 0, count: 0, hasNew: false }
    a.managers.add(m.manager)
    a.value += m.value
    a.count += 1
    if (m.action === 'NEW') a.hasNew = true
    map.set(m.ticker, a)
  }
  return [...map.entries()].map(([ticker, a]) => ({
    ticker, managers: a.managers.size, value: a.value, count: a.count, hasNew: a.hasNew,
  }))
}

function aggManagers(moves: FundMove[]): ManagerAgg[] {
  const map = new Map<string, ManagerAgg>()
  for (const m of moves) {
    const a = map.get(m.manager) ?? { manager: m.manager, value: 0, news: 0, adds: 0, count: 0 }
    a.value += m.value
    a.count += 1
    if (m.action === 'NEW') a.news += 1
    else a.adds += 1
    map.set(m.manager, a)
  }
  return [...map.values()]
}

// ── Most-crowded names (conviction by manager count) ────────────────────────────

function CrowdedNames({ rows, onPick }: { rows: TickerAgg[]; onPick: (t: string) => void }) {
  const view = [...rows].sort((a, b) => b.managers - a.managers || b.value - a.value).slice(0, 10)
  if (view.length === 0) return <div className="num py-6 text-center text-[11px] text-faint">NO DATA</div>
  const maxCount = Math.max(1, ...view.map(r => r.managers))
  return (
    <div className="space-y-2.5">
      {view.map(r => {
        const pct = (r.managers / maxCount) * 100
        return (
          <div key={r.ticker} className="grid items-center gap-3" style={{ gridTemplateColumns: '88px 1fr 120px' }}>
            <button onClick={() => onPick(r.ticker)} className="flex items-center gap-1.5 text-left">
              <TickerLogo ticker={r.ticker} size={18} className="shrink-0" />
              <span className="num text-[11px] font-semibold text-cyan hover:underline">{r.ticker}</span>
            </button>
            <div className="relative h-[6px] overflow-hidden rounded-full bg-border/30">
              <div className="absolute inset-y-0 left-0 rounded-full transition-all duration-500"
                style={{ width: `${pct}%`, background: 'linear-gradient(90deg, rgba(34,211,238,0.7) 0%, rgba(34,211,238,0.2) 100%)' }} />
            </div>
            <div className="flex items-center justify-end gap-2">
              <span className="num text-[10px] text-muted">{r.managers} {r.managers === 1 ? 'fund' : 'funds'}</span>
              <span className="num text-[9px] text-faint">{fmtUsd(r.value)}</span>
              {r.hasNew && <span className="num rounded-sm border border-up/30 bg-up/10 px-1 py-px text-[7px] font-bold tracking-widest text-up">NEW</span>}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ── Biggest bets (by capital) ────────────────────────────────────────────────────

function BiggestBets({ rows, onPick }: { rows: TickerAgg[]; onPick: (t: string) => void }) {
  const view = [...rows].sort((a, b) => b.value - a.value).slice(0, 10)
  if (view.length === 0) return <div className="num py-6 text-center text-[11px] text-faint">NO DATA</div>
  const maxVal = Math.max(1, ...view.map(r => r.value))
  return (
    <div className="space-y-2.5">
      {view.map(r => {
        const pct = (r.value / maxVal) * 100
        return (
          <div key={r.ticker} className="grid items-center gap-3" style={{ gridTemplateColumns: '88px 1fr 96px' }}>
            <button onClick={() => onPick(r.ticker)} className="flex items-center gap-1.5 text-left">
              <TickerLogo ticker={r.ticker} size={18} className="shrink-0" />
              <span className="num text-[11px] font-semibold text-cyan hover:underline">{r.ticker}</span>
            </button>
            <div className="relative h-[6px] overflow-hidden rounded-full bg-border/30">
              <div className="absolute inset-y-0 left-0 rounded-full transition-all duration-500"
                style={{ width: `${pct}%`, background: 'linear-gradient(90deg, rgba(34,197,94,0.7) 0%, rgba(34,197,94,0.2) 100%)' }} />
            </div>
            <div className="flex items-center justify-end gap-2">
              <span className="num text-[10px] text-up">{fmtUsd(r.value)}</span>
              <span className="num text-[9px] text-faint">{r.count}×</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ── Manager leaderboard (click to filter the feed) ──────────────────────────────

function ManagerBoard({ rows, selected, onSelect }: {
  rows: ManagerAgg[]; selected: string | null; onSelect: (m: string | null) => void
}) {
  const view = [...rows].sort((a, b) => b.value - a.value).slice(0, 12)
  if (view.length === 0) return <div className="num py-6 text-center text-[11px] text-faint">NO DATA</div>
  return (
    <div className="flex flex-col">
      {view.map(r => {
        const total = r.news + r.adds
        const newPct = total > 0 ? (r.news / total) * 100 : 0
        const active = selected === r.manager
        return (
          <button
            key={r.manager}
            onClick={() => onSelect(active ? null : r.manager)}
            className={cn('border-b border-border-dim py-1.5 text-left transition-colors hover:bg-bg-hover',
              active && 'bg-cyan/5')}
          >
            <div className="flex items-baseline justify-between gap-2">
              <span className={cn('truncate font-sans text-[11px]', active ? 'text-cyan' : 'text-ink')}>{r.manager}</span>
              <span className="num shrink-0 text-[10px] text-up">{fmtUsd(r.value)}</span>
            </div>
            <div className="mt-1 flex h-1.5 w-full overflow-hidden bg-border/40">
              <div className="h-full bg-up/60" style={{ width: `${newPct}%` }} />
              <div className="h-full bg-cyan/60" style={{ width: `${100 - newPct}%` }} />
            </div>
            <div className="mt-0.5 flex justify-between">
              <span className="num text-[9px] text-up">{r.news} new</span>
              <span className="num text-[9px] text-cyan">{r.adds} add{r.adds === 1 ? '' : 's'}</span>
            </div>
          </button>
        )
      })}
    </div>
  )
}

// ── Conviction map (crowding × capital bubble scatter) ───────────────────────────

interface MapPoint { ticker: string; label: string; x: number; y: number; z: number; hasNew: boolean }

function ConvictionTooltip({ active, payload }: {
  active?: boolean; payload?: { payload: MapPoint }[]
}) {
  if (!active || !payload?.length) return null
  const p = payload[0].payload
  return (
    <div className="border border-border bg-bg-panel px-2.5 py-1.5 font-mono text-[11px]">
      <div className="font-semibold text-cyan">{p.ticker}</div>
      <div className="text-muted">{p.x} {p.x === 1 ? 'fund' : 'funds'} · {fmtUsd(p.y)}</div>
      {p.hasNew && <div className="text-up">new position opened</div>}
    </div>
  )
}

function ConvictionMap({ rows }: { rows: TickerAgg[] }) {
  const { points, ticks } = useMemo(() => {
    const top = new Set([...rows].sort((a, b) => b.value - a.value).slice(0, 14).map(r => r.ticker))
    const pts: MapPoint[] = rows.map(r => ({
      ticker: r.ticker,
      label: top.has(r.ticker) ? r.ticker : '',
      x: r.managers,
      y: r.value,
      z: r.value,
      hasNew: r.hasNew,
    }))
    const maxX = Math.max(1, ...pts.map(p => p.x))
    return { points: pts, ticks: Array.from({ length: maxX }, (_, i) => i + 1) }
  }, [rows])

  if (points.length === 0) {
    return <div className="num flex h-64 items-center justify-center text-[11px] text-faint">NO DATA</div>
  }
  return (
    <div className="h-64">
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 12, right: 16, bottom: 18, left: 8 }}>
          <XAxis
            type="number" dataKey="x" name="funds" ticks={ticks} domain={[0.5, 'dataMax+0.5']}
            stroke="#4b5563" fontSize={10} fontFamily="var(--font-mono)" tickLine={false} allowDecimals={false}
            label={{ value: 'FUNDS IN THE NAME →', position: 'insideBottom', offset: -8, fill: '#4b5563', fontSize: 9, fontFamily: 'var(--font-mono)' }}
          />
          <YAxis
            type="number" dataKey="y" name="capital" scale="log" domain={['auto', 'auto']}
            stroke="#4b5563" fontSize={10} fontFamily="var(--font-mono)" tickLine={false} axisLine={false} width={48}
            tickFormatter={(v: number) => fmtUsd(v)}
          />
          <ZAxis type="number" dataKey="z" range={[60, 900]} />
          <Tooltip cursor={{ strokeDasharray: '3 3', stroke: '#4b5563' }} content={<ConvictionTooltip />} />
          <Scatter data={points} isAnimationActive={false}>
            {points.map(p => (
              <Cell
                key={p.ticker}
                fill={p.hasNew ? 'rgba(34,197,94,0.45)' : 'rgba(34,211,238,0.4)'}
                stroke={p.hasNew ? '#22c55e' : '#22d3ee'}
                strokeWidth={1}
              />
            ))}
            <LabelList dataKey="label" position="top" fill="#9ca3af" fontSize={9} fontFamily="var(--font-mono)" />
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  )
}

// ── Main ─────────────────────────────────────────────────────────────────────────

export function Whales() {
  const { data, isLoading, error } = useFunds(null)
  const moves = useMemo(() => data?.moves ?? [], [data])
  const [modalTicker, setModalTicker] = useState<string | null>(null)
  const [selectedManager, setSelectedManager] = useState<string | null>(null)
  const [actionFilter, setActionFilter] = useState<'ALL' | 'NEW' | 'ADD'>('ALL')
  const [expanded, setExpanded] = useState<number | null>(null)

  const tickers = useMemo(() => aggTickers(moves), [moves])
  const managers = useMemo(() => aggManagers(moves), [moves])

  const totals = useMemo(() => ({
    moves: moves.length,
    news: moves.filter(m => m.action === 'NEW').length,
    adds: moves.filter(m => m.action === 'ADD').length,
    managers: new Set(moves.map(m => m.manager)).size,
    tickers: new Set(moves.map(m => m.ticker)).size,
    capital: moves.reduce((s, m) => s + m.value, 0),
  }), [moves])

  const feed = useMemo(() => moves.filter(m =>
    (selectedManager == null || m.manager === selectedManager) &&
    (actionFilter === 'ALL' || m.action === actionFilter),
  ), [moves, selectedManager, actionFilter])

  if (isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <span className="num text-sm text-muted">LOADING 13F FILINGS…</span>
      </div>
    )
  }
  if (error) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <span className="num text-sm text-down">FAILED TO LOAD — {String(error)}</span>
      </div>
    )
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">

      {/* ── KPI bar ─────────────────────────────────────── */}
      <div className="flex shrink-0 items-stretch border-b border-border bg-bg-panel">
        <Kpi label="DISCLOSED BUYS" value={totals.moves || '—'} sub="LATEST 13F MOVES" tone={totals.moves ? 'cyan' : 'muted'} />
        <Kpi label="NEW POSITIONS" value={totals.news || '—'} sub="FRESH CONVICTION" tone="up" />
        <Kpi label="ADD-ONS" value={totals.adds || '—'} sub="BUILT ON A STAKE" tone="cyan" />
        <Kpi label="FUNDS ACTIVE" value={totals.managers || '—'} sub="HEDGE FUNDS + MANAGERS" tone="muted" />
        <Kpi label="NAMES BOUGHT" value={totals.tickers || '—'} sub="UNIQUE TICKERS" tone="muted" />
        <Kpi label="CAPITAL DEPLOYED" value={fmtUsd(totals.capital)} sub="DISCLOSED POSITION $" tone="warn" />
      </div>

      <HowToPanel />

      {/* ── Filter toolbar ─────────────────────────────── */}
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border bg-bg-panel px-4 py-2">
        <Fish className="h-3.5 w-3.5 text-cyan" />
        <span className="label text-[9px]">SHOW</span>
        {(['ALL', 'NEW', 'ADD'] as const).map(a => (
          <button
            key={a}
            onClick={() => setActionFilter(a)}
            className={cn('num border px-2.5 py-0.5 text-[10px] font-semibold transition-colors',
              actionFilter === a ? 'border-cyan text-cyan' : 'border-border text-faint hover:border-border-bright hover:text-muted')}
          >
            {a === 'ALL' ? 'ALL BUYS' : a === 'NEW' ? 'NEW ONLY' : 'ADD-ONS'}
          </button>
        ))}
        {selectedManager && (
          <button
            onClick={() => setSelectedManager(null)}
            className="num ml-1 flex items-center gap-1 border border-cyan/40 bg-cyan/10 px-2 py-0.5 text-[10px] font-semibold text-cyan"
          >
            {selectedManager}
            <X className="h-3 w-3" />
          </button>
        )}
      </div>

      {totals.moves === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2">
          <span className="num text-sm text-muted">NO FUND DATA YET</span>
          <p className="max-w-xs text-center font-sans text-[12px] text-faint">
            Run <span className="num text-cyan">cortex funds-sync</span> or hit SYNC DATA on the dashboard.
          </p>
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto p-4">
          <div className="grid items-start gap-4 lg:grid-cols-2">

            {/* Conviction map */}
            <section className="border border-border bg-bg-panel p-3 lg:col-span-2">
              <div className="mb-2 flex items-baseline gap-2">
                <span className="num text-[11px] font-semibold tracking-widest text-cyan">CONVICTION MAP</span>
                <span className="font-sans text-[10px] text-faint">
                  each dot is a stock · right = more funds piled in · up = more capital · green = a brand-new position
                </span>
              </div>
              <ConvictionMap rows={tickers} />
            </section>

            {/* Most crowded */}
            <section className="border border-border bg-bg-panel p-3">
              <div className="mb-3 flex items-baseline gap-2">
                <span className="num text-[11px] font-semibold tracking-widest text-cyan">MOST CROWDED NAMES</span>
                <span className="font-sans text-[10px] text-faint">how many funds are in the same stock · ticker → open</span>
              </div>
              <CrowdedNames rows={tickers} onPick={setModalTicker} />
            </section>

            {/* Biggest bets */}
            <section className="border border-border bg-bg-panel p-3">
              <div className="mb-3 flex items-baseline gap-2">
                <span className="num text-[11px] font-semibold tracking-widest text-cyan">BIGGEST BETS</span>
                <span className="font-sans text-[10px] text-faint">ranked by disclosed position $ · ticker → open</span>
              </div>
              <BiggestBets rows={tickers} onPick={setModalTicker} />
            </section>

            {/* Manager leaderboard */}
            <section className="border border-border bg-bg-panel p-3 lg:col-span-2">
              <div className="mb-2 flex items-baseline gap-2">
                <span className="num text-[11px] font-semibold tracking-widest text-cyan">WHO'S BUYING</span>
                <span className="font-sans text-[10px] text-faint">by capital deployed · bar = new vs add · click a fund to filter the feed</span>
              </div>
              <ManagerBoard rows={managers} selected={selectedManager} onSelect={setSelectedManager} />
            </section>

            {/* Recent moves feed */}
            <section className="border border-border bg-bg-panel p-3 lg:col-span-2">
              <div className="mb-2 flex items-baseline gap-2">
                <span className="num text-[11px] font-semibold tracking-widest text-cyan">RECENT MOVES</span>
                <span className="font-sans text-[10px] text-faint">{feed.length} shown</span>
                <span className="font-sans text-[10px] text-faint">· ▸ expand to see the stock price when they filed and how it's moved since</span>
              </div>
              <table className="w-full border-collapse">
                <thead>
                  <tr className="border-b border-border text-left">
                    <th className="label px-2 py-1.5 w-6" />
                    <th className="label px-2 py-1.5">ACTION</th>
                    <th className="label px-2 py-1.5">TICKER</th>
                    <th className="label px-2 py-1.5">FUND</th>
                    <th className="label px-2 py-1.5 text-right">POSITION</th>
                    <th className="label px-2 py-1.5 text-right">CHANGE</th>
                    <th className="label px-2 py-1.5 text-right">AS OF</th>
                  </tr>
                </thead>
                <tbody>
                  {feed.map((m, i) => {
                    const isOpen = expanded === i
                    const isNew = m.action === 'NEW'
                    return (
                      <Fragment key={`${m.manager}-${m.ticker}-${i}`}>
                      <tr className={cn('border-b border-border-dim hover:bg-bg-hover', isOpen && 'bg-bg-hover')}>
                        <td className="px-2 py-1.5">
                          <button onClick={() => setExpanded(isOpen ? null : i)} className="text-faint hover:text-cyan" title="Show price since filing">
                            {isOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                          </button>
                        </td>
                        <td className="px-2 py-1.5">
                          <span className={cn('num text-[9px] font-bold tracking-widest', isNew ? 'text-up' : 'text-cyan')}>{m.action}</span>
                        </td>
                        <td className="px-2 py-1.5">
                          <button onClick={() => setModalTicker(m.ticker)} className="flex items-center gap-1.5 text-left">
                            <TickerLogo ticker={m.ticker} size={16} className="shrink-0" />
                            <span className="num text-[11px] font-semibold text-cyan hover:underline">{m.ticker}</span>
                          </button>
                        </td>
                        <td className="px-2 py-1.5 font-sans text-[11px] text-muted">{m.manager}</td>
                        <td className="num px-2 py-1.5 text-right text-[11px] text-up">{fmtUsd(m.value)}</td>
                        <td className="num px-2 py-1.5 text-right text-[10px] text-up">
                          {isNew ? 'new' : m.pct_change != null ? `+${(m.pct_change * 100).toFixed(0)}%` : '—'}
                        </td>
                        <td className="num px-2 py-1.5 text-right text-[10px] text-faint">{fmtDate(m.period)}</td>
                      </tr>
                      {isOpen && (
                        <tr>
                          <td colSpan={7} className="p-0">
                            <TradeImpactChart
                              ticker={m.ticker}
                              tradeDate={filingDate(m.period)}
                              side="buy"
                              markerLabel="FILED"
                            />
                          </td>
                        </tr>
                      )}
                      </Fragment>
                    )
                  })}
                </tbody>
              </table>
              {feed.length === 0 && (
                <div className="num py-6 text-center text-[11px] text-faint">NO MOVES MATCH THIS FILTER</div>
              )}
            </section>

          </div>
        </div>
      )}

      {modalTicker && <StockModal ticker={modalTicker} onClose={() => setModalTicker(null)} />}
    </div>
  )
}
