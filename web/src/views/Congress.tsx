import { useMemo, useState } from 'react'
import {
  Bar,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { ChevronDown, ChevronRight, ExternalLink, HelpCircle, Landmark } from 'lucide-react'

import { useCongress, useCongressStats } from '@/lib/api'
import type { CongressMemberStat, CongressTickerStat } from '@/lib/types'
import { TickerLogo } from '@/components/ui/TickerLogo'
import { cn, fmtCompact, fmtDate } from '@/lib/utils'
import { StockModal } from '@/views/StockModal'

const fmtUsd = (v: number | null | undefined): string =>
  v == null || Number.isNaN(v) ? '—' : `$${fmtCompact(v)}`

const monthLabel = (m: string): string => {
  const [y, mo] = m.split('-')
  const names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  return `${names[Number(mo) - 1] ?? mo} ${y.slice(2)}`
}

// ── KPI tile (matches AriSpecial) ─────────────────────────────────────────────

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

// ── How-to / explainer panel ──────────────────────────────────────────────────

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
            — every stock trade U.S. senators are <span className="text-muted">legally required to disclose</span>, aggregated into buy/sell flow
          </span>
        )}
      </button>

      {open && (
        <div className="border-t border-border-dim bg-bg px-5 pb-5 pt-4">
          <div className="mb-4 grid gap-4 lg:grid-cols-3">
            <div className="border-l-2 border-cyan/30 pl-3">
              <div className="num mb-1 text-[11px] font-semibold text-cyan">Where it comes from</div>
              <p className="font-sans text-[11px] leading-snug text-faint">
                The 2012 <span className="text-muted">STOCK Act</span> forces every senator to file a Periodic
                Transaction Report within <span className="text-muted">45 days</span> of any stock trade. This page
                mirrors those filings from the Senate eFD system.
              </p>
            </div>
            <div className="border-l-2 border-warn/30 pl-3">
              <div className="num mb-1 text-[11px] font-semibold text-warn">Why disclosure date, not trade date</div>
              <p className="font-sans text-[11px] leading-snug text-faint">
                A trade is only <span className="text-muted">public knowledge</span> once it's filed. Flow is gated on
                the disclosure date so the signal never peeks at information you couldn't have acted on. The lag below
                shows how stale that information typically is.
              </p>
            </div>
            <div className="border-l-2 border-up/30 pl-3">
              <div className="num mb-1 text-[11px] font-semibold text-up">Dollar amounts are ranges</div>
              <p className="font-sans text-[11px] leading-snug text-faint">
                Filings report brackets like <span className="text-muted">"$50,001 – $100,000"</span>, never an exact
                figure. Every dollar total here uses the <span className="text-muted">midpoint</span> of the bracket, so
                treat notionals as estimates of scale, not precise cash.
              </p>
            </div>
          </div>
          <div className="border border-cyan/20 bg-cyan/5 px-4 py-3">
            <div className="num mb-1 text-[10px] font-semibold tracking-widest text-cyan">THE CONGRESS FACTOR</div>
            <p className="font-sans text-[12px] leading-relaxed text-muted max-w-3xl">
              CORTEX builds a net-buy signal from this data: net senator buying in a name (decayed with a 180-day
              half-life) is tested against forward returns. As of the last backtest it scores a{' '}
              <span className="text-ink font-medium">t-stat of 2.40</span> — real, but below the{' '}
              <span className="text-ink font-medium">t ≥ 3.0</span> pre-registration bar, so it informs research but
              does not drive live trades.
            </p>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Monthly buy/sell flow ──────────────────────────────────────────────────────

function FlowChart({ data }: { data: { month: string; buy: number; sell: number; net: number }[] }) {
  if (data.length === 0) {
    return <div className="num flex h-56 items-center justify-center text-[11px] text-faint">NO TIMELINE DATA</div>
  }
  return (
    <div className="h-56">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
          <XAxis dataKey="month" stroke="#4b5563" fontSize={10} fontFamily="var(--font-mono)"
            tickLine={false} interval="preserveStartEnd" />
          <YAxis stroke="#4b5563" fontSize={10} fontFamily="var(--font-mono)" tickLine={false}
            axisLine={false} width={48} tickFormatter={(v: number) => `$${fmtCompact(Math.abs(v))}`} />
          <ReferenceLine y={0} stroke="#4b5563" />
          <Tooltip
            contentStyle={{
              background: 'var(--color-bg-panel)', border: '1px solid var(--color-border)',
              borderRadius: '2px', fontFamily: 'var(--font-mono)', fontSize: '11px',
            }}
            formatter={(value, name) => {
              const labels: Record<string, string> = { buy: 'buys', sell: 'sells', net: 'net' }
              return [`$${fmtCompact(Math.abs(Number(value)))}`, labels[String(name)] ?? String(name)]
            }}
          />
          <Bar dataKey="buy" fill="#22c55e" fillOpacity={0.55} isAnimationActive={false} />
          <Bar dataKey="sell" fill="#ef4444" fillOpacity={0.55} isAnimationActive={false} />
          <Line dataKey="net" stroke="#22d3ee" strokeWidth={1.5} dot={false} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

// ── Per-ticker member drill-down (expanded row) ────────────────────────────────

function TickerMembers({ ticker, days }: { ticker: string; days: number }) {
  const { data, isLoading } = useCongress(ticker, days)

  const members = useMemo(() => {
    const agg = new Map<string, { senator: string; buy: number; sell: number; count: number }>()
    for (const tr of data?.trades ?? []) {
      const m = agg.get(tr.senator) ?? { senator: tr.senator, buy: 0, sell: 0, count: 0 }
      if (tr.transaction_type.toLowerCase().includes('purchase')) m.buy += 1
      else m.sell += 1
      m.count += 1
      agg.set(tr.senator, m)
    }
    return [...agg.values()].sort((a, b) => b.count - a.count)
  }, [data])

  if (isLoading) {
    return <div className="num py-2 pl-8 text-[10px] text-faint">LOADING MEMBERS…</div>
  }
  if (members.length === 0) {
    return <div className="num py-2 pl-8 text-[10px] text-faint">NO MEMBER DETAIL</div>
  }
  return (
    <div className="grid gap-x-6 gap-y-0.5 py-2 pl-8 pr-2 sm:grid-cols-2">
      {members.map(m => (
        <div key={m.senator} className="flex items-baseline justify-between gap-2 border-b border-border-dim py-0.5">
          <span className="truncate font-sans text-[11px] text-muted">{m.senator}</span>
          <span className="num shrink-0 text-[10px]">
            {m.buy > 0 && <span className="text-up">{m.buy} buy</span>}
            {m.buy > 0 && m.sell > 0 && <span className="text-faint"> · </span>}
            {m.sell > 0 && <span className="text-down">{m.sell} sell</span>}
          </span>
        </div>
      ))}
    </div>
  )
}

// ── Top tickers (diverging buy/sell bars + drill-down) ──────────────────────────

type TickerSort = 'net' | 'buys' | 'sells' | 'count' | 'consensus'

const TICKER_SORTS: { key: TickerSort; label: string }[] = [
  { key: 'net', label: 'Net flow' },
  { key: 'buys', label: 'Buy $' },
  { key: 'sells', label: 'Sell $' },
  { key: 'count', label: 'Trades' },
  { key: 'consensus', label: 'Buyers' },
]

function tickerSortValue(r: CongressTickerStat, k: TickerSort): number {
  switch (k) {
    case 'buys': return r.buy_notional
    case 'sells': return r.sell_notional
    case 'count': return r.count
    case 'consensus': return r.buyers
    default: return Math.abs(r.net_notional)
  }
}

function TopTickers({ rows, onPick, days }: {
  rows: CongressTickerStat[]; onPick: (t: string) => void; days: number
}) {
  const [sortKey, setSortKey] = useState<TickerSort>('net')
  const [expanded, setExpanded] = useState<string | null>(null)

  const view = useMemo(
    () => [...rows].sort((a, b) => tickerSortValue(b, sortKey) - tickerSortValue(a, sortKey)).slice(0, 15),
    [rows, sortKey],
  )
  const maxGross = Math.max(1, ...view.map(r => Math.max(r.buy_notional, r.sell_notional)))

  return (
    <div>
      {/* Sort toggle + legend */}
      <div className="mb-1.5 flex flex-wrap items-center gap-1">
        <span className="label text-[9px]">SORT</span>
        {TICKER_SORTS.map(s => (
          <button
            key={s.key}
            onClick={() => setSortKey(s.key)}
            className={cn(
              'num border px-1.5 py-0.5 text-[9px] font-semibold transition-colors',
              sortKey === s.key
                ? 'border-cyan text-cyan'
                : 'border-border text-faint hover:border-border-bright hover:text-muted',
            )}
          >
            {s.label}
          </button>
        ))}
        <span className="num ml-auto text-[9px] text-faint">
          <span className="text-down">← sells</span> · <span className="text-up">buys →</span>
        </span>
      </div>

      <div className="flex flex-col">
        {view.map(r => {
          const buying = r.net_notional >= 0
          const sellFrac = (r.sell_notional / maxGross) * 50
          const buyFrac = (r.buy_notional / maxGross) * 50
          const isOpen = expanded === r.ticker
          return (
            <div key={r.ticker} className="border-b border-border-dim">
              <div className="flex items-center gap-2 py-1.5">
                <button
                  onClick={() => setExpanded(isOpen ? null : r.ticker)}
                  className="shrink-0 text-faint hover:text-muted"
                  title="Show members"
                >
                  {isOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                </button>
                <button
                  onClick={() => onPick(r.ticker)}
                  className="flex w-[88px] shrink-0 items-center gap-1.5 text-left"
                >
                  <TickerLogo ticker={r.ticker} size={18} className="shrink-0" />
                  <span className="num text-[11px] font-semibold text-cyan hover:underline">{r.ticker}</span>
                </button>
                {/* Diverging buy/sell bar */}
                <div className="relative h-3 flex-1 bg-border/30" title={`${fmtUsd(r.buy_notional)} bought · ${fmtUsd(r.sell_notional)} sold`}>
                  <div className="absolute left-1/2 top-0 h-full w-px bg-border-bright" />
                  <div className="absolute top-0 h-full bg-down/60" style={{ right: '50%', width: `${sellFrac}%` }} />
                  <div className="absolute top-0 h-full bg-up/60" style={{ left: '50%', width: `${buyFrac}%` }} />
                </div>
                <span className={cn('num w-16 shrink-0 text-right text-[11px]', buying ? 'text-up' : 'text-down')}>
                  {buying ? '+' : '−'}{fmtUsd(Math.abs(r.net_notional)).slice(1)}
                </span>
                <span className="num w-12 shrink-0 text-right text-[10px]">
                  <span className="text-up">{r.buyers}</span>
                  <span className="text-faint">/</span>
                  <span className="text-down">{r.sellers}</span>
                </span>
                <span className="num w-7 shrink-0 text-right text-[10px] text-faint">{r.count}×</span>
              </div>
              {isOpen && <TickerMembers ticker={r.ticker} days={days} />}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Top members ────────────────────────────────────────────────────────────────

function TopMembers({ rows }: { rows: CongressMemberStat[] }) {
  return (
    <div className="flex flex-col">
      {rows.map(r => {
        const total = r.buy_notional + r.sell_notional
        const buyPct = total > 0 ? (r.buy_notional / total) * 100 : 0
        return (
          <div key={r.senator} className="border-b border-border-dim py-1.5">
            <div className="flex items-baseline justify-between gap-2">
              <span className="truncate font-sans text-[11px] text-ink">{r.senator}</span>
              <span className="num shrink-0 text-[10px] text-faint">{r.count} filings</span>
            </div>
            <div className="mt-1 flex h-1.5 w-full overflow-hidden bg-border/40">
              <div className="h-full bg-up/60" style={{ width: `${buyPct}%` }} />
              <div className="h-full bg-down/60" style={{ width: `${100 - buyPct}%` }} />
            </div>
            <div className="mt-0.5 flex justify-between">
              <span className="num text-[9px] text-up">{fmtUsd(r.buy_notional)} buys</span>
              <span className="num text-[9px] text-down">{fmtUsd(r.sell_notional)} sells</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ── Disclosure-lag strip ─────────────────────────────────────────────────────────

function LagStrip({ lag }: { lag: Record<string, number> }) {
  const order = ['<=30', '31-45', '46-90', '>90']
  const labels: Record<string, string> = { '<=30': '≤30d', '31-45': '31–45d', '46-90': '46–90d', '>90': '>90d' }
  const tones: Record<string, string> = { '<=30': 'bg-up/60', '31-45': 'bg-cyan/60', '46-90': 'bg-warn/60', '>90': 'bg-down/60' }
  const total = Math.max(1, order.reduce((s, k) => s + (lag[k] ?? 0), 0))
  return (
    <div>
      <div className="flex h-3 w-full overflow-hidden bg-border/40">
        {order.map(k => (
          <div key={k} className={tones[k]} style={{ width: `${((lag[k] ?? 0) / total) * 100}%` }} />
        ))}
      </div>
      <div className="mt-1.5 grid grid-cols-4 gap-2">
        {order.map(k => (
          <div key={k} className="flex items-center gap-1.5">
            <span className={cn('h-2 w-2 shrink-0', tones[k])} />
            <span className="num text-[10px] text-faint">{labels[k]}</span>
            <span className="num ml-auto text-[10px] text-muted">{lag[k] ?? 0}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Window selector ──────────────────────────────────────────────────────────────

const WINDOWS = [
  { label: '90D', value: 90 },
  { label: '180D', value: 180 },
  { label: '1Y', value: 365 },
  { label: '2Y', value: 730 },
]

// ── Main ─────────────────────────────────────────────────────────────────────────

export function Congress() {
  const [days, setDays] = useState(365)
  const { data, isLoading, error } = useCongressStats(days)
  const { data: feed } = useCongress(null, days)
  const [modalTicker, setModalTicker] = useState<string | null>(null)

  const flow = useMemo(
    () =>
      (data?.timeline ?? []).map(m => ({
        month: monthLabel(m.month),
        buy: m.buy_notional,
        sell: -m.sell_notional,
        net: m.buy_notional - m.sell_notional,
      })),
    [data],
  )

  if (isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <span className="num text-sm text-muted">LOADING CONGRESSIONAL FILINGS…</span>
      </div>
    )
  }

  const t = data?.totals
  const buyTilt = t && t.trades > 0 ? Math.round((t.buys / t.trades) * 100) : null

  return (
    <div className="flex flex-1 flex-col overflow-hidden">

      {/* ── KPI bar ─────────────────────────────────────── */}
      <div className="flex shrink-0 items-stretch border-b border-border bg-bg-panel">
        <Kpi label="DISCLOSED TRADES" value={t?.trades ?? '—'} sub={`LAST ${days} DAYS`}
          tone={t?.trades ? 'cyan' : 'muted'} />
        <Kpi label="BUY / SELL TILT" value={buyTilt != null ? `${buyTilt}%` : '—'}
          sub={t ? `${t.buys} buys · ${t.sells} sells` : 'BUYS OF ALL TRADES'}
          tone={buyTilt != null ? (buyTilt >= 50 ? 'up' : 'down') : 'muted'} />
        <Kpi label="EST. BUY VOLUME" value={fmtUsd(t?.buy_notional)} sub="MIDPOINT NOTIONAL" tone="up" />
        <Kpi label="EST. SELL VOLUME" value={fmtUsd(t?.sell_notional)} sub="MIDPOINT NOTIONAL" tone="down" />
        <Kpi label="ACTIVE MEMBERS" value={t?.members ?? '—'} sub={`${t?.tickers ?? 0} TICKERS`} tone="muted" />
        <Kpi label="MEDIAN LAG" value={t?.median_disclosure_lag_days != null ? `${t.median_disclosure_lag_days}d` : '—'}
          sub="TRADE → DISCLOSURE" tone="warn" />
      </div>

      <HowToPanel />

      {/* ── Window toolbar ─────────────────────────────── */}
      <div className="flex shrink-0 items-center gap-2 border-b border-border bg-bg-panel px-4 py-2">
        <Landmark className="h-3.5 w-3.5 text-cyan" />
        <span className="label text-[9px]">WINDOW</span>
        {WINDOWS.map(w => (
          <button
            key={w.value}
            onClick={() => setDays(w.value)}
            className={cn(
              'num border px-2.5 py-0.5 text-[10px] font-semibold transition-colors',
              days === w.value
                ? 'border-cyan text-cyan'
                : 'border-border text-faint hover:border-border-bright hover:text-muted',
            )}
          >
            {w.label}
          </button>
        ))}
      </div>

      {error ? (
        <div className="flex flex-1 items-center justify-center">
          <span className="num text-sm text-down">FAILED TO LOAD — {String(error)}</span>
        </div>
      ) : !t || t.trades === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2">
          <span className="num text-sm text-muted">NO CONGRESS DATA YET</span>
          <p className="max-w-xs text-center font-sans text-[12px] text-faint">
            Run <span className="num text-cyan">wst congress-sync</span> or hit refresh on the dashboard.
          </p>
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto p-4">
          <div className="grid items-start gap-4 lg:grid-cols-2">

            {/* Flow timeline */}
            <section className="border border-border bg-bg-panel p-3 lg:col-span-2">
              <div className="mb-2 flex items-baseline gap-2">
                <span className="num text-[11px] font-semibold tracking-widest text-cyan">MONTHLY BUY / SELL FLOW</span>
                <span className="font-sans text-[10px] text-faint">
                  green = buying · red = selling · cyan line = net (by disclosure month)
                </span>
              </div>
              <FlowChart data={flow} />
            </section>

            {/* Left column: top tickers + disclosure lag */}
            <div className="flex flex-col gap-4">
              <section className="border border-border bg-bg-panel p-3">
                <div className="mb-2 flex items-baseline gap-2">
                  <span className="num text-[11px] font-semibold tracking-widest text-cyan">CONGRESS FLOW BY TICKER</span>
                  <span className="font-sans text-[10px] text-faint">net $ · buyers/sellers · ▸ expand · ticker → open</span>
                </div>
                <TopTickers rows={data.top_tickers} onPick={setModalTicker} days={days} />
              </section>

              <section className="border border-border bg-bg-panel p-3">
                <div className="mb-2 flex items-baseline gap-2">
                  <span className="num text-[11px] font-semibold tracking-widest text-cyan">DISCLOSURE LAG</span>
                  <span className="font-sans text-[10px] text-faint">days from trade to public filing</span>
                </div>
                <LagStrip lag={data.disclosure_lag} />
                <p className="mt-3 font-sans text-[10px] leading-snug text-faint">
                  The STOCK Act caps this at 45 days. Anything in the red bucket is a filing that arrived later than the
                  law allows — and the longer the lag, the staler the signal by the time you can act on it.
                </p>
              </section>
            </div>

            {/* Right column: most active members */}
            <section className="border border-border bg-bg-panel p-3">
              <div className="mb-2 flex items-baseline gap-2">
                <span className="num text-[11px] font-semibold tracking-widest text-cyan">MOST ACTIVE MEMBERS</span>
                <span className="font-sans text-[10px] text-faint">by filing count · bar = buy/sell split</span>
              </div>
              <TopMembers rows={data.top_members} />
            </section>

            {/* Recent feed */}
            <section className="border border-border bg-bg-panel p-3 lg:col-span-2">
              <div className="mb-2 flex items-baseline gap-2">
                <span className="num text-[11px] font-semibold tracking-widest text-cyan">RECENT FILINGS</span>
                <span className="font-sans text-[10px] text-faint">{feed?.count ?? 0} most-recent disclosures</span>
              </div>
              <table className="w-full border-collapse">
                <thead>
                  <tr className="border-b border-border text-left">
                    <th className="label px-2 py-1.5">MEMBER</th>
                    <th className="label px-2 py-1.5">TICKER</th>
                    <th className="label px-2 py-1.5">ACTION</th>
                    <th className="label px-2 py-1.5 text-right">AMOUNT</th>
                    <th className="label px-2 py-1.5 text-right">TRADED</th>
                    <th className="label px-2 py-1.5 text-right">DISCLOSED</th>
                    <th className="label px-2 py-1.5" />
                  </tr>
                </thead>
                <tbody>
                  {(feed?.trades ?? []).map((tr, i) => {
                    const buy = tr.transaction_type.toLowerCase().includes('purchase')
                    return (
                      <tr key={`${tr.ticker}-${i}`} className="border-b border-border-dim hover:bg-bg-hover">
                        <td className="px-2 py-1.5 font-sans text-[11px] text-muted">{tr.senator}</td>
                        <td className="px-2 py-1.5">
                          <button
                            onClick={() => setModalTicker(tr.ticker)}
                            className="num text-[11px] font-semibold text-cyan hover:underline"
                          >
                            {tr.ticker}
                          </button>
                        </td>
                        <td className={cn('num px-2 py-1.5 text-[11px]', buy ? 'text-up' : 'text-down')}>
                          {buy ? 'BUY' : 'SELL'}
                        </td>
                        <td className="num px-2 py-1.5 text-right text-[11px] text-faint">{tr.amount}</td>
                        <td className="num px-2 py-1.5 text-right text-[10px] text-faint">{fmtDate(tr.transaction_date)}</td>
                        <td className="num px-2 py-1.5 text-right text-[10px] text-muted">{fmtDate(tr.disclosure_date)}</td>
                        <td className="px-2 py-1.5 text-right">
                          {tr.report_url && (
                            <a href={tr.report_url} target="_blank" rel="noreferrer"
                              className="inline-flex text-faint hover:text-cyan">
                              <ExternalLink className="h-3 w-3" />
                            </a>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </section>

          </div>
        </div>
      )}

      {modalTicker && <StockModal ticker={modalTicker} onClose={() => setModalTicker(null)} />}
    </div>
  )
}
