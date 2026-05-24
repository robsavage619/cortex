import { Fragment, useMemo, useState } from 'react'
import {
  Area,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { ChevronDown, ChevronRight, HelpCircle } from 'lucide-react'

import { useCase, useHistory, useVolatilityScreen } from '@/lib/api'
import type { VolStock } from '@/lib/types'
import { TickerLogo } from '@/components/ui/TickerLogo'
import type { CasePoint } from '@/lib/types'
import { cn, fmtCompact, fmtDate, fmtPercent, fmtPrice } from '@/lib/utils'
import { StockModal } from '@/views/StockModal'

// ── Cortex case panel (expanded row) ─────────────────────────────────────────

function CortexCase({ ticker }: { ticker: string }) {
  const { data, isLoading } = useCase(ticker)
  const c = data?.case

  if (isLoading) {
    return (
      <div className="num mt-3 border-t border-border-dim pt-3 text-[10px] text-faint">
        LOADING CORTEX CASE…
      </div>
    )
  }
  if (!c) return null

  const toneClass = (z: number) =>
    z >= 0.5 ? 'text-up' : z <= -0.5 ? 'text-down' : 'text-muted'

  const Point = ({ p }: { p: CasePoint }) => (
    <div className="flex gap-2">
      <span className={cn('num mt-px shrink-0 text-[10px] font-bold', toneClass(p.z))}>
        {p.z >= 0 ? '+' : ''}{p.z.toFixed(1)}σ
      </span>
      <span className="font-sans text-[11px] leading-snug text-muted">{p.argument}</span>
    </div>
  )

  return (
    <div className="mt-3 border-t border-border-dim pt-3">
      <div className="mb-2 flex items-baseline gap-2">
        <span className="num text-[10px] font-semibold tracking-widest text-cyan">CORTEX</span>
        <span className="font-sans text-[11px] text-muted">{c.headline}</span>
      </div>
      <div className="grid gap-x-6 gap-y-1 sm:grid-cols-2">
        {c.bull_points.slice(0, 3).map((p, i) => <Point key={i} p={p} />)}
        {c.risk_points.slice(0, 2).map((p, i) => <Point key={i} p={p} />)}
      </div>
    </div>
  )
}

// ── KPI tile ────────────────────────────────────────────────────────────────

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

// ── How-to panel ─────────────────────────────────────────────────────────────

const METRICS: { term: string; plain: string; accent: string }[] = [
  {
    term: 'Daily Swing ($)',
    plain: 'How many dollars the stock typically moves between its low and high in a single day. A $10 swing means there\'s $10 of range to work with.',
    accent: 'text-warn border-warn/30',
  },
  {
    term: 'Swing %',
    plain: 'The same swing expressed as a percentage of price. Lets you fairly compare a $50 stock against a $500 one — both might move 3% even if the dollar amounts look very different.',
    accent: 'text-muted border-border-bright',
  },
  {
    term: 'Consistency',
    plain: 'How similar the swing size is from one day to the next. A score near 1.0 means it swings roughly the same amount every day — predictable. Near 0 means some days it\'s huge, other days barely moves.',
    accent: 'text-up border-up/30',
  },
  {
    term: 'Bouncy vs Trendy',
    plain: 'Whether the stock bounces back and forth inside a range (great for swing trading) or steadily drifts in one direction (a trend). Higher = more back-and-forth. "BOUNCERS ONLY" filters to stocks scoring 0.7+.',
    accent: 'text-cyan border-cyan/30',
  },
  {
    term: 'Position in Range',
    plain: 'Where the latest closing price sits between the recent low and high. Near the bottom of the range might mean a bounce up is coming; near the top might be a fade back down.',
    accent: 'text-muted border-border-bright',
  },
]

function HowToPanel() {
  const [open, setOpen] = useState(false)
  return (
    <div className="shrink-0 border-b border-border">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex w-full items-center gap-2 px-5 py-2 text-left transition-colors hover:bg-bg-hover"
      >
        <HelpCircle className="h-3.5 w-3.5 text-cyan" />
        <span className="num text-[11px] font-semibold tracking-[0.1em] text-cyan">HOW TO READ THIS PAGE</span>
        {open ? <ChevronDown className="h-3.5 w-3.5 text-faint" /> : <ChevronRight className="h-3.5 w-3.5 text-faint" />}
        {!open && (
          <span className="font-sans text-[11px] text-faint">
            — stocks ranked by <span className="text-muted">dollar swing × consistency</span> · click any row to see the swing pattern
          </span>
        )}
      </button>

      {open && (
        <div className="border-t border-border-dim bg-bg px-5 pb-5 pt-4">

          {/* Score formula callout */}
          <div className="mb-4 flex flex-wrap items-start gap-5 border border-cyan/20 bg-cyan/5 px-4 py-3">
            <div className="min-w-0">
              <div className="num mb-1 text-[10px] font-semibold tracking-widest text-cyan">THE SCORE</div>
              <div className="flex flex-wrap items-center gap-2">
                <span className="num rounded border border-warn/40 bg-warn/10 px-2 py-0.5 text-[13px] font-bold text-warn">Swing % of Price</span>
                <span className="num text-[14px] font-bold text-muted">×</span>
                <span className="num rounded border border-up/40 bg-up/10 px-2 py-0.5 text-[13px] font-bold text-up">Consistency</span>
                <span className="num text-[14px] font-bold text-muted">=</span>
                <span className="num rounded border border-cyan/40 bg-cyan/10 px-2 py-0.5 text-[13px] font-bold text-cyan">Score</span>
              </div>
            </div>
            <p className="font-sans text-[12px] leading-relaxed text-muted max-w-xl">
              A stock earns a high score by swinging a <span className="text-ink font-medium">large % of its price</span> AND doing it{' '}
              <span className="text-ink font-medium">roughly the same size every day</span>. Raw dollar size doesn't matter —
              a $50 stock that swings 8% beats a $500 stock that only swings 2%, even though the dollar amounts look different.
              In the S&P 500, elite swingers run <span className="text-ink font-medium">5–9% daily</span>;
              the MIN SWING % filter defaults to 3% to cut the dull names while keeping a workable list.
            </p>
          </div>

          {/* Metric glossary */}
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
            {METRICS.map(m => (
              <div key={m.term} className={`border-l-2 pl-3 ${m.accent.split(' ')[1] ?? 'border-border'}`}>
                <div className={`num mb-1 text-[11px] font-semibold ${m.accent.split(' ')[0] ?? 'text-ink'}`}>{m.term}</div>
                <div className="font-sans text-[11px] leading-snug text-faint">{m.plain}</div>
              </div>
            ))}
          </div>

        </div>
      )}
    </div>
  )
}

// ── The daily-swing chart (expanded row) ──────────────────────────────────────

const PERIODS: { label: string; value: string }[] = [
  { label: '1D', value: '1d' },
  { label: '1W', value: '5d' },
  { label: '1M', value: '1mo' },
  { label: '1Y', value: '1y' },
]

function SwingChart({ ticker }: { ticker: string }) {
  const [period, setPeriod] = useState('1mo')
  const { data: bars = [], isLoading } = useHistory(ticker, period)

  const data = useMemo(
    () =>
      bars.map(b => ({
        date: period === '1d'
          ? b.date.slice(11, 16)   // HH:MM for intraday
          : period === '5d'
            ? b.date.slice(5, 10)  // MM-DD
            : period === '1mo'
              ? b.date.slice(5)    // MM-DD
              : b.date.slice(0, 7), // YYYY-MM for 1y
        band: [b.low, b.high] as [number, number],
        close: b.close,
      })),
    [bars, period],
  )

  return (
    <div>
      {/* Period tabs */}
      <div className="mb-2 flex items-center gap-1">
        {PERIODS.map(p => (
          <button
            key={p.value}
            onClick={() => setPeriod(p.value)}
            className={cn(
              'num border px-2 py-0.5 text-[10px] font-semibold transition-colors',
              period === p.value
                ? 'border-cyan text-cyan'
                : 'border-border text-faint hover:border-border-bright hover:text-muted',
            )}
          >
            {p.label}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="num flex h-44 items-center justify-center text-[11px] text-faint">LOADING…</div>
      ) : data.length === 0 ? (
        <div className="num flex h-44 items-center justify-center text-[11px] text-faint">NO PRICE DATA</div>
      ) : (
        <div className="h-44">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={data} margin={{ top: 4, right: 12, bottom: 4, left: 0 }}>
              <XAxis dataKey="date" stroke="#4b5563" fontSize={10}
                fontFamily="var(--font-mono)" tickLine={false} interval="preserveStartEnd" />
              <YAxis stroke="#4b5563" fontSize={10} fontFamily="var(--font-mono)"
                tickLine={false} axisLine={false} domain={['auto', 'auto']}
                tickFormatter={(v: number) => `$${v.toFixed(0)}`} width={44} />
              <Tooltip
                contentStyle={{
                  background: 'var(--color-bg-panel)',
                  border: '1px solid var(--color-border)',
                  borderRadius: '2px',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '11px',
                }}
                formatter={(value, name) => {
                  if (name === 'band' && Array.isArray(value)) {
                    return [`$${value[0].toFixed(2)} → $${value[1].toFixed(2)}`, 'day range']
                  }
                  return [`$${Number(value).toFixed(2)}`, 'close']
                }}
              />
              <Area dataKey="band" stroke="#22d3ee" strokeOpacity={0.35}
                fill="#22d3ee" fillOpacity={0.12} isAnimationActive={false} />
              <Line dataKey="close" stroke="#22d3ee" strokeWidth={1.5} dot={false}
                isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}
      <p className="mt-1 max-w-xl font-sans text-[10px] leading-snug text-faint">
        Each shaded band is one day's low→high range. Bands of{' '}
        <span className="text-muted">similar height all the way across</span> = steady,
        predictable swing. The bright line is the closing price.
      </p>
    </div>
  )
}

// ── Mini horizontal meters ─────────────────────────────────────────────────────

function Meter({ value, tone }: { value: number; tone: string }) {
  return (
    <div className="h-1 w-16 bg-border">
      <div className={cn('h-full transition-all', tone)}
        style={{ width: `${Math.min(100, Math.max(0, value * 100))}%` }} />
    </div>
  )
}

function RangePositionDot({ pos }: { pos: number }) {
  return (
    <div className="relative h-1 w-16 bg-border">
      <div
        className="absolute top-1/2 h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-cyan"
        style={{ left: `${Math.min(100, Math.max(0, pos * 100))}%` }}
      />
    </div>
  )
}

// ── Plain-English per-stock readout ────────────────────────────────────────────

function plainReadout(s: VolStock): string {
  const parts: string[] = []
  if (s.avg_dollar_range != null) {
    parts.push(`Swings about ${fmtPrice(s.avg_dollar_range)} between low and high on a typical day`)
  }
  if (s.oscillation_score != null) {
    parts.push(
      s.oscillation_score >= 0.7
        ? 'and tends to bounce back and forth rather than trend'
        : s.oscillation_score >= 0.45
          ? 'with a mix of bouncing and drifting'
          : 'but lately it has been drifting in one direction more than bouncing',
    )
  }
  let sentence = parts.join(' ') + '.'
  if (s.range_position != null) {
    const where = s.range_position <= 0.25 ? 'near the bottom of'
      : s.range_position >= 0.75 ? 'near the top of'
        : 'around the middle of'
    sentence += ` Right now it's sitting ${where} its recent range.`
  }
  return sentence
}

// ── Sorting ─────────────────────────────────────────────────────────────────

type SortKey = 'score' | 'adr' | 'pct' | 'max_pct' | 'consistency' | 'oscillation' | 'price'

const SORTS: { key: SortKey; label: string }[] = [
  { key: 'score', label: 'Best overall (score)' },
  { key: 'adr', label: 'Biggest $ swing' },
  { key: 'pct', label: 'Biggest avg % swing' },
  { key: 'max_pct', label: 'Biggest peak % swing' },
  { key: 'consistency', label: 'Most consistent' },
  { key: 'oscillation', label: 'Most bouncy' },
  { key: 'price', label: 'Share price' },
]

function sortValue(s: VolStock, key: SortKey): number {
  switch (key) {
    case 'adr': return s.avg_dollar_range ?? 0
    case 'pct': return s.avg_range_pct ?? 0
    case 'max_pct': return s.max_range_pct ?? 0
    case 'consistency': return s.range_consistency ?? 0
    case 'oscillation': return s.oscillation_score ?? 0
    case 'price': return s.avg_close ?? 0
    default: return s.ari_special_score
  }
}

// ── Main ────────────────────────────────────────────────────────────────────

export function AriSpecial() {
  const { data, isLoading, error } = useVolatilityScreen()
  const [modalTicker, setModalTicker] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)

  const [search, setSearch] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('score')
  const [minPrice, setMinPrice] = useState('')
  const [minSwingPct, setMinSwingPct] = useState('3')
  const [minSwingDollar, setMinSwingDollar] = useState('5')
  const [swingersOnly, setSwingersOnly] = useState(false)

  const stocks = data?.stocks ?? []
  const lookback = data?.lookback_days ?? 15

  const view = useMemo(() => {
    const q = search.trim().toUpperCase()
    const priceFloor = Number(minPrice) || 0
    const swingFloor = (Number(minSwingPct) || 0) / 100
    const dollarFloor = Number(minSwingDollar) || 0
    return stocks
      .filter(s => (q ? s.ticker.includes(q) || (s.company_name ?? '').toUpperCase().includes(q) : true))
      .filter(s => (priceFloor > 0 ? (s.avg_close ?? 0) >= priceFloor : true))
      .filter(s => (swingFloor > 0 ? (s.avg_range_pct ?? 0) >= swingFloor : true))
      .filter(s => (dollarFloor > 0 ? (s.avg_dollar_range ?? 0) >= dollarFloor : true))
      .filter(s => (swingersOnly ? (s.oscillation_score ?? 0) >= 0.7 : true))
      .sort((a, b) => sortValue(b, sortKey) - sortValue(a, sortKey))
  }, [stocks, search, minPrice, minSwingPct, minSwingDollar, swingersOnly, sortKey])

  if (isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <span className="num text-sm text-muted">SCANNING UNIVERSE…</span>
      </div>
    )
  }

  const topScore = stocks[0]?.ari_special_score
  const widestAdr = stocks.reduce<number>((m, s) => Math.max(m, s.avg_dollar_range ?? 0), 0)

  return (
    <div className="flex flex-1 flex-col overflow-hidden">

      {/* ── KPI bar ─────────────────────────────────────── */}
      <div className="flex shrink-0 items-stretch border-b border-border bg-bg-panel">
        <Kpi label="MATCHES" value={stocks.length} sub={`${lookback} TRADING DAYS`}
          tone={stocks.length > 0 ? 'cyan' : 'muted'} />
        <Kpi label="TOP SCORE" value={topScore != null ? topScore.toFixed(1) : '—'}
          sub="SWING % × CONSISTENCY" tone={topScore != null ? 'up' : 'muted'} />
        <Kpi label="WIDEST SWING" value={widestAdr > 0 ? fmtPrice(widestAdr) : '—'}
          sub="AVG DAILY HIGH→LOW" tone={widestAdr > 0 ? 'warn' : 'muted'} />
        <Kpi label="LAST UPDATED" value={data?.last_run ? fmtDate(data.last_run) : '—'}
          sub="REFRESH ON DASHBOARD" tone="muted" />
      </div>

      <HowToPanel />

      {/* ── Toolbar ─────────────────────────────────────── */}
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border bg-bg-panel px-4 py-2">
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search ticker or name…"
          className="num h-6 w-44 border border-border bg-bg px-2 text-[11px] text-ink placeholder:text-faint focus:border-cyan focus:outline-none"
        />
        <div className="flex items-center gap-1.5 border-l border-border pl-2">
          <span className="label text-[9px]">SORT</span>
          <select
            value={sortKey}
            onChange={e => setSortKey(e.target.value as SortKey)}
            className="num h-6 border border-border bg-bg px-1.5 text-[11px] text-ink focus:border-cyan focus:outline-none"
          >
            {SORTS.map(s => <option key={s.key} value={s.key}>{s.label}</option>)}
          </select>
        </div>
        <div className="flex items-center gap-1.5 border-l border-border pl-2">
          <span className="label text-[9px]">MIN SWING $</span>
          <input
            value={minSwingDollar}
            onChange={e => setMinSwingDollar(e.target.value.replace(/[^0-9.]/g, ''))}
            placeholder="0"
            className="num h-6 w-10 border border-border bg-bg px-2 text-[11px] text-ink placeholder:text-faint focus:border-cyan focus:outline-none"
          />
        </div>
        <div className="flex items-center gap-1.5 border-l border-border pl-2">
          <span className="label text-[9px]">MIN SWING %</span>
          <input
            value={minSwingPct}
            onChange={e => setMinSwingPct(e.target.value.replace(/[^0-9.]/g, ''))}
            placeholder="0"
            className="num h-6 w-10 border border-border bg-bg px-2 text-[11px] text-ink placeholder:text-faint focus:border-cyan focus:outline-none"
          />
        </div>
        <div className="flex items-center gap-1.5 border-l border-border pl-2">
          <span className="label text-[9px]">MIN PRICE $</span>
          <input
            value={minPrice}
            onChange={e => setMinPrice(e.target.value.replace(/[^0-9.]/g, ''))}
            placeholder="any"
            className="num h-6 w-12 border border-border bg-bg px-2 text-[11px] text-ink placeholder:text-faint focus:border-cyan focus:outline-none"
          />
        </div>
        <div className="border-l border-border pl-2">
          <button
            onClick={() => setSwingersOnly(v => !v)}
            className={cn(
              'num h-6 border px-2.5 text-[10px] font-semibold tracking-wider transition-colors',
              swingersOnly
                ? 'border-cyan bg-bg-selected text-cyan'
                : 'border-border text-muted hover:border-border-bright hover:text-ink',
            )}
          >
            BOUNCERS ONLY
          </button>
        </div>
        <span className="num ml-auto text-[10px] text-faint">
          {view.length} / {stocks.length}
        </span>
      </div>

      {error ? (
        <div className="flex flex-1 items-center justify-center">
          <span className="num text-sm text-down">SCREEN FAILED — {String(error)}</span>
        </div>
      ) : stocks.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2">
          <span className="num text-sm text-muted">NO SCREEN DATA YET</span>
          <p className="max-w-xs text-center font-sans text-[12px] text-faint">
            Run <span className="num text-cyan">wst vol-screen</span> or hit refresh on the dashboard.
          </p>
        </div>
      ) : view.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2">
          <span className="num text-sm text-muted">NO MATCHES</span>
          <p className="max-w-sm text-center font-sans text-[12px] text-faint">
            Your filters are too tight. In the S&P 500 universe the best daily swing % is{' '}
            <span className="num text-warn">
              {((stocks.reduce((m, s) => Math.max(m, s.avg_range_pct ?? 0), 0)) * 100).toFixed(1)}%
            </span>{' '}
            and the biggest dollar swing is{' '}
            <span className="num text-warn">
              {fmtPrice(stocks.reduce((m, s) => Math.max(m, s.avg_dollar_range ?? 0), 0))}
            </span>.
            Try lowering MIN SWING % or MIN SWING $.
          </p>
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto">
          <table className="w-full border-collapse">
            <thead className="sticky top-0 z-10 bg-bg-panel">
              <tr className="border-b border-border text-left">
                <th className="label px-3 py-1.5 w-6" />
                <th className="label px-3 py-1.5">TICKER</th>
                <th className="label px-3 py-1.5 text-right">SCORE</th>
                <th className="label px-3 py-1.5 text-right">DAILY SWING</th>
                <th className="label px-3 py-1.5 text-right">AVG SWING %</th>
                <th className="label px-3 py-1.5 text-right">PEAK SWING $</th>
                <th className="label px-3 py-1.5 text-right">PEAK SWING %</th>
                <th className="label px-3 py-1.5">CONSISTENCY</th>
                <th className="label px-3 py-1.5">BOUNCY</th>
                <th className="label px-3 py-1.5">RANGE POS</th>
                <th className="label px-3 py-1.5 text-right">PRICE</th>
              </tr>
            </thead>
            <tbody>
              {view.map(s => {
                const cons = s.range_consistency ?? 0
                const osc = s.oscillation_score ?? 0
                const pos = s.range_position ?? 0.5
                const isOpen = expanded === s.ticker
                return (
                  <Fragment key={s.ticker}>
                    <tr
                      onClick={() => setExpanded(isOpen ? null : s.ticker)}
                      className="cursor-pointer border-b border-border-dim transition-colors hover:bg-bg-hover"
                    >
                      <td className="px-3 py-2 text-faint">
                        {isOpen
                          ? <ChevronDown className="h-3 w-3" />
                          : <ChevronRight className="h-3 w-3" />}
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-2">
                          <TickerLogo ticker={s.ticker} size={22} className="shrink-0" />
                          <div className="min-w-0">
                            <button
                              onClick={e => { e.stopPropagation(); setModalTicker(s.ticker) }}
                              className="num block text-[12px] font-semibold leading-tight text-cyan hover:underline"
                            >
                              {s.ticker}
                            </button>
                            {s.company_name && (
                              <div className="truncate font-sans text-[10px] leading-tight text-faint max-w-[140px]">
                                {s.company_name}
                              </div>
                            )}
                          </div>
                        </div>
                      </td>
                      <td className="num px-3 py-2 text-right text-[12px] text-ink">
                        {s.ari_special_score.toFixed(1)}
                      </td>
                      <td className="num px-3 py-2 text-right text-[12px] text-warn">
                        {fmtPrice(s.avg_dollar_range)}
                      </td>
                      <td className="num px-3 py-2 text-right text-[11px] text-muted">
                        {fmtPercent(s.avg_range_pct)}
                      </td>
                      <td className="num px-3 py-2 text-right text-[12px]">
                        {s.max_dollar_range != null ? (
                          <span className="text-warn">{fmtPrice(s.max_dollar_range)}</span>
                        ) : '—'}
                      </td>
                      <td className="num px-3 py-2 text-right text-[11px]">
                        {s.max_range_pct != null ? (
                          <span className={s.max_range_pct >= 0.10 ? 'text-up' : 'text-muted'}>
                            {fmtPercent(s.max_range_pct)}
                          </span>
                        ) : '—'}
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-2">
                          <Meter value={cons} tone={cons >= 0.6 ? 'bg-up' : cons >= 0.45 ? 'bg-warn' : 'bg-down'} />
                          <span className="num text-[10px] text-faint">{cons.toFixed(2)}</span>
                        </div>
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-2">
                          <Meter value={osc} tone={osc >= 0.7 ? 'bg-up' : osc >= 0.45 ? 'bg-warn' : 'bg-down'} />
                          <span className="num w-10 text-[10px] text-faint">
                            {osc >= 0.7 ? 'swings' : osc >= 0.45 ? 'mixed' : 'trends'}
                          </span>
                        </div>
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-2">
                          <RangePositionDot pos={pos} />
                          <span className="num w-6 text-[10px] text-faint">
                            {pos <= 0.25 ? 'low' : pos >= 0.75 ? 'high' : 'mid'}
                          </span>
                        </div>
                      </td>
                      <td className="num px-3 py-2 text-right text-[11px] text-muted">
                        {fmtPrice(s.avg_close)}
                      </td>
                    </tr>
                    {isOpen && (
                      <tr className="border-b border-border-dim bg-bg">
                        <td colSpan={11} className="px-5 py-3">
                          <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
                            <SwingChart ticker={s.ticker} />
                            <div className="flex flex-col gap-2.5">
                              <div className="flex items-center gap-2.5">
                                <TickerLogo ticker={s.ticker} size={28} />
                                <div>
                                  <div className="num text-[13px] font-semibold leading-tight text-ink">{s.ticker}</div>
                                  {s.company_name && (
                                    <div className="font-sans text-[11px] leading-tight text-muted">{s.company_name}</div>
                                  )}
                                </div>
                              </div>
                              <p className="font-sans text-[12px] leading-relaxed text-muted">
                                {plainReadout(s)}
                              </p>
                              <div className="grid grid-cols-2 gap-x-4 gap-y-1">
                                <Stat label="Avg volume / day" value={s.avg_volume != null ? fmtCompact(s.avg_volume) : '—'} />
                                <Stat label="Direction flips" value={s.direction_changes ?? '—'} />
                                <Stat label="Net drift (window)" value={fmtPercent(s.net_drift_pct)} />
                                <Stat label="Avg close" value={fmtPrice(s.avg_close)} />
                              </div>
                              <button
                                onClick={() => setModalTicker(s.ticker)}
                                className="num w-fit border border-cyan px-3 py-1 text-[10px] font-semibold tracking-wider text-cyan transition-colors hover:bg-cyan hover:text-bg"
                              >
                                OPEN FULL STOCK VIEW →
                              </button>
                              <CortexCase ticker={s.ticker} />
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {modalTicker && <StockModal ticker={modalTicker} onClose={() => setModalTicker(null)} />}
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex items-baseline justify-between gap-2 border-b border-border-dim pb-1">
      <span className="font-sans text-[10px] text-faint">{label}</span>
      <span className="num text-[11px] text-ink">{value}</span>
    </div>
  )
}
