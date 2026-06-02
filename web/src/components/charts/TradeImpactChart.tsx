import { useMemo } from 'react'
import {
  Area,
  AreaChart,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { useHistory } from '@/lib/api'
import { cn, fmtPrice } from '@/lib/utils'

type Side = 'buy' | 'sell'

interface Props {
  ticker: string
  /** ISO date (YYYY-MM-DD) the trade was executed, or quarter-end for 13F filings. */
  tradeDate: string | null
  side: Side
  /** Optional label for the marker, e.g. "FILED Q1 2024". Defaults to "TRADE". */
  markerLabel?: string
}

/** Pick a yfinance period that comfortably spans from the trade date to today. */
function periodForAge(tradeDate: string): string {
  const ageDays = (Date.now() - new Date(tradeDate).getTime()) / 86_400_000
  if (ageDays <= 25) return '3mo'
  if (ageDays <= 80) return '6mo'
  if (ageDays <= 200) return '1y'
  if (ageDays <= 360) return '2y'
  if (ageDays <= 700) return '5y'
  return 'max'
}

function Stat({ label, value, sub, tone }: {
  label: string; value: string; sub?: string; tone?: 'up' | 'down' | 'cyan' | 'muted'
}) {
  const colors = { up: 'text-up', down: 'text-down', cyan: 'text-cyan', muted: 'text-ink' }
  return (
    <div className="flex flex-col gap-0.5">
      <span className="label text-[9px]">{label}</span>
      <span className={cn('num text-base font-semibold leading-none', colors[tone ?? 'muted'])}>{value}</span>
      {sub && <span className="num text-[9px] text-faint">{sub}</span>}
    </div>
  )
}

/**
 * Annotated "what happened next" chart for a single disclosed trade.
 *
 * Fetches OHLC history spanning the trade date, snaps the trade to the nearest
 * trading day, and renders a price area with the entry marked — plus the price
 * then vs. now and the return since, framed in plain language.
 */
export function TradeImpactChart({ ticker, tradeDate, side, markerLabel = 'TRADE' }: Props) {
  const period = tradeDate ? periodForAge(tradeDate) : '1y'
  const { data: bars, isLoading, error } = useHistory(ticker, period)

  const model = useMemo(() => {
    if (!tradeDate || !bars || bars.length === 0) return null
    // bars are oldest-first, date = "YYYY-MM-DD"
    let entryIdx = -1
    for (let i = 0; i < bars.length; i++) {
      if (bars[i].date <= tradeDate) entryIdx = i
      else break
    }
    if (entryIdx === -1) entryIdx = 0
    const entry = bars[entryIdx]
    const latest = bars[bars.length - 1]
    if (!entry || !latest || entry.close <= 0) return null

    const pct = (latest.close / entry.close - 1) * 100
    const rose = latest.close >= entry.close
    const aligned = side === 'buy' ? pct >= 0 : pct <= 0

    const preroll = Math.min(20, entryIdx)
    const series = bars.slice(entryIdx - preroll).map(b => ({ date: b.date, close: b.close }))

    return { entry, latest, pct, rose, aligned, series }
  }, [bars, tradeDate, side])

  if (!tradeDate) {
    return <div className="num py-4 pl-8 text-[10px] text-faint">NO TRADE DATE ON FILE — CANNOT PRICE</div>
  }
  if (isLoading) {
    return <div className="num py-4 pl-8 text-[10px] text-faint">PRICING {ticker} AROUND {tradeDate}…</div>
  }
  if (error || !model) {
    return <div className="num py-4 pl-8 text-[10px] text-faint">NO PRICE HISTORY FOR {ticker}</div>
  }

  const { entry, latest, pct, rose, aligned, series } = model
  const lineColor = rose ? '#22c55e' : '#ef4444'
  const signed = `${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%`

  // Plain-language verdict (Rob prefers plain English over quant jargon).
  const verb = side === 'buy' ? 'Bought' : 'Sold'
  const move = rose ? `up ${Math.abs(pct).toFixed(0)}%` : `down ${Math.abs(pct).toFixed(0)}%`
  const judgment =
    side === 'buy'
      ? rose ? 'The timing looked good — the stock climbed afterward.'
             : "It's slipped since they bought in."
      : rose ? 'The stock kept rising after they sold — gains left on the table.'
             : 'They stepped out before the drop.'
  const verdict = `${verb} ${ticker} near ${fmtPrice(entry.close)} on ${entry.date} — it's ${move} since. ${judgment}`

  return (
    <div className="border-t border-border-dim bg-bg px-4 py-3 pl-8">
      <div className="grid items-center gap-4 md:grid-cols-[260px_1fr]">
        {/* Stat block */}
        <div className="grid grid-cols-3 gap-3">
          <Stat label="PRICE AT TRADE" value={fmtPrice(entry.close)} sub={entry.date} tone="cyan" />
          <Stat label="PRICE NOW" value={fmtPrice(latest.close)} sub={latest.date} tone="muted" />
          <Stat label="SINCE TRADE" value={signed} sub={aligned ? 'went their way' : 'went against'} tone={aligned ? 'up' : 'down'} />
        </div>

        {/* Annotated price area */}
        <div className="h-32">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={series} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id={`grad-${ticker}-${entry.date}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={lineColor} stopOpacity={0.35} />
                  <stop offset="100%" stopColor={lineColor} stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="date" stroke="#4b5563" fontSize={9} fontFamily="var(--font-mono)"
                tickLine={false} axisLine={false} interval="preserveStartEnd" minTickGap={48}
                tickFormatter={(d: string) => d.slice(2)} />
              <YAxis stroke="#4b5563" fontSize={9} fontFamily="var(--font-mono)" tickLine={false}
                axisLine={false} width={44} domain={['auto', 'auto']}
                tickFormatter={(v: number) => `$${v.toFixed(0)}`} />
              <Tooltip
                contentStyle={{
                  background: 'var(--color-bg-panel)', border: '1px solid var(--color-border)',
                  borderRadius: '2px', fontFamily: 'var(--font-mono)', fontSize: '11px',
                }}
                labelStyle={{ color: 'var(--color-faint)' }}
                formatter={(value) => [fmtPrice(Number(value)), 'close']}
              />
              <Area dataKey="close" stroke={lineColor} strokeWidth={1.5} fill={`url(#grad-${ticker}-${entry.date})`}
                isAnimationActive={false} />
              <ReferenceLine x={entry.date} stroke="#f59e0b" strokeDasharray="3 3"
                label={{ value: markerLabel, position: 'insideTopLeft', fill: '#f59e0b', fontSize: 9, fontFamily: 'var(--font-mono)' }} />
              <ReferenceDot x={entry.date} y={entry.close} r={4} fill="#f59e0b" stroke="var(--color-bg)" strokeWidth={1.5} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>
      <p className="mt-2 font-sans text-[11px] leading-snug text-faint">{verdict}</p>
    </div>
  )
}
