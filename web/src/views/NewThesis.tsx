import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { TrendingDown, TrendingUp } from 'lucide-react'

import { Button } from '@/components/ui/Button'
import { Input, Label, Select, Textarea } from '@/components/ui/Field'
import { useCalibration, useCreateThesis, useTickerContext } from '@/lib/api'
import { cn, fmtPercent, fmtPrice, fmtSignedPercent } from '@/lib/utils'

// ── Live price anchor ─────────────────────────────────────────────────────────

function PriceAnchor({ ticker }: { ticker: string }) {
  const { data, isLoading } = useTickerContext(ticker || null)
  const price  = data?.market?.price ?? null
  const change = data?.market?.day_change_percent ?? null
  const up     = (change ?? 0) >= 0

  if (!ticker) return null
  if (isLoading) return (
    <div className="border border-border bg-bg-panel px-4 py-3">
      <span className="num text-[11px] text-muted">FETCHING {ticker.toUpperCase()}…</span>
    </div>
  )
  if (!price) return null

  return (
    <div className="border border-border-bright bg-bg-panel px-4 py-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="num text-sm font-bold text-ink">{ticker.toUpperCase()}</span>
          <span className={cn('num text-lg font-semibold', up ? 'text-up' : 'text-down')}>
            {fmtPrice(price)}
          </span>
          <span className={cn('num text-[12px] inline-flex items-center gap-1', up ? 'text-up' : 'text-down')}>
            {up ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
            {fmtSignedPercent(change)}
          </span>
        </div>
        {data?.market?.pe_ratio != null && (
          <span className="num text-[11px] text-faint">P/E {data.market.pe_ratio.toFixed(1)}×</span>
        )}
      </div>
      <p className="font-sans mt-1.5 text-[10px] text-faint">
        Neutral price anchor — not a recommendation. Shown to reduce anchoring bias on entry.
      </p>
    </div>
  )
}

// ── Section divider ───────────────────────────────────────────────────────────

function Section({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="border-b border-border pt-2 pb-3">
      <span className="label block">{title}</span>
      {subtitle && <p className="font-sans mt-0.5 text-[11px] text-faint">{subtitle}</p>}
    </div>
  )
}

// ── Conviction calibration nudge ──────────────────────────────────────────────

const MIN_RELIABLE = 5 // buckets below this many reviews are statistical noise

function ConvictionNudge({ conviction }: { conviction: number }) {
  const { data } = useCalibration()
  const bucket = data?.buckets.find(b => b.conviction === conviction)

  if (!bucket || bucket.total === 0) {
    return (
      <p className="num mt-2 text-[10px] text-faint">
        NO TRACK RECORD AT {conviction}/5 YET — NUDGE UNLOCKS ONCE YOU REVIEW THESES AT THIS LEVEL
      </p>
    )
  }

  const expected = conviction / 5
  const gap = bucket.hit_rate - expected
  const reliable = bucket.total >= MIN_RELIABLE
  const overconfident = reliable && gap < -0.1

  return (
    <div className={cn(
      'mt-2 border-l-2 px-3 py-2',
      overconfident ? 'border-warn bg-warn/5' : reliable ? 'border-up bg-up/5' : 'border-border-bright',
    )}>
      <p className="num text-[11px] text-ink">
        YOUR {conviction}/5 CALLS HIT{' '}
        <span className={cn('font-semibold', overconfident ? 'text-warn' : reliable ? 'text-up' : 'text-muted')}>
          {fmtPercent(bucket.hit_rate, 0)}
        </span>{' '}
        <span className="text-faint">({bucket.correct}/{bucket.total})</span> · TARGET {fmtPercent(expected, 0)}
      </p>
      {overconfident && (
        <p className="font-sans mt-1 text-[10px] text-warn">
          Overconfident at this level by {fmtPercent(-gap, 0)} — consider dialing conviction down.
        </p>
      )}
      {!reliable && (
        <p className="font-sans mt-1 text-[10px] text-faint">
          Small sample ({bucket.total}/{MIN_RELIABLE}) — read as directional, not statistical.
        </p>
      )}
    </div>
  )
}

// ── New Thesis form ───────────────────────────────────────────────────────────

export function NewThesis() {
  const navigate = useNavigate()
  const create   = useCreateThesis()

  // Core fields
  const [tickers,     setTickers]     = useState('')
  const [author,      setAuthor]      = useState('rob')
  const [conviction,  setConviction]  = useState(3)
  const [claim,       setClaim]       = useState('')
  const [falsifier,   setFalsifier]   = useState('')
  const [reasoning,   setReasoning]   = useState('')
  const [reviewDate,  setReviewDate]  = useState('')
  const [entryPrice,  setEntryPrice]  = useState('')

  // Pre-commitment fields
  const [baseRate,       setBaseRate]       = useState('')
  const [preMortem,      setPreMortem]      = useState('')
  const [changeMyMind,   setChangeMyMind]   = useState('')
  const [sizingRationale,setSizingRationale]= useState('')
  const [whyNow,         setWhyNow]         = useState('')

  // Cooling-off
  const [coolingOff,     setCoolingOff]     = useState(false)
  const [coolingHours,   setCoolingHours]   = useState(24)

  // Live price anchor — debounced ticker
  const [anchorTicker, setAnchorTicker] = useState('')
  useEffect(() => {
    const t = setTimeout(() => {
      const first = tickers.split(',')[0]?.trim().toUpperCase()
      setAnchorTicker(first ?? '')
    }, 600)
    return () => clearTimeout(t)
  }, [tickers])

  const valid = tickers.trim() && claim.trim() && falsifier.trim() && reviewDate

  const CONV_LABEL = ['', 'LOW', 'LOW-MED', 'MEDIUM', 'MED-HIGH', 'HIGH']

  function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!valid) return
    create.mutate(
      {
        tickers: tickers.split(',').map(t => t.trim().toUpperCase()).filter(Boolean),
        author,
        conviction,
        claim:            claim.trim(),
        falsifier:        falsifier.trim(),
        reasoning:        reasoning.trim() || null,
        review_date:      reviewDate,
        entry_price:      entryPrice ? Number(entryPrice) : null,
        base_rate:        baseRate.trim()        || null,
        pre_mortem:       preMortem.trim()       || null,
        change_my_mind:   changeMyMind.trim()    || null,
        sizing_rationale: sizingRationale.trim() || null,
        why_now:          whyNow.trim()          || null,
        cooling_off_hours: coolingOff ? coolingHours : null,
      },
      { onSuccess: t => navigate(`/thesis/${t.id}`) },
    )
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">

      {/* Header */}
      <div className="flex shrink-0 items-center justify-between border-b border-border bg-bg-panel px-5 py-3">
        <div>
          <span className="num text-sm font-semibold text-ink">NEW THESIS</span>
          <span className="font-sans ml-3 text-[12px] text-faint">State a falsifiable claim and what would prove it wrong.</span>
        </div>
        <button onClick={() => navigate(-1)} className="num text-[10px] tracking-widest text-muted hover:text-ink">
          ← CANCEL
        </button>
      </div>

      <form onSubmit={submit} className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-2xl space-y-5 px-5 py-6">

          {/* ── Core ──────────────────────────────────────── */}
          <Section title="CORE" subtitle="Required fields. These define the bet." />

          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="tickers">TICKERS</Label>
              <Input id="tickers" placeholder="AAPL, MSFT" value={tickers}
                onChange={e => setTickers(e.target.value)} />
            </div>
            <div>
              <Label htmlFor="author">AUTHOR</Label>
              <Select id="author" value={author} onChange={e => setAuthor(e.target.value)}>
                <option value="rob">rob</option>
                <option value="ari">ari</option>
              </Select>
            </div>
          </div>

          {/* Live price anchor */}
          {anchorTicker && <PriceAnchor ticker={anchorTicker} />}

          <div>
            <Label htmlFor="claim">CLAIM</Label>
            <Textarea id="claim" placeholder="What do you believe will happen, and by when?"
              value={claim} onChange={e => setClaim(e.target.value)} />
          </div>

          <div>
            <Label htmlFor="falsifier">INVALIDATED IF ⚡</Label>
            <Textarea id="falsifier" placeholder="What specific, observable fact would prove this thesis wrong?"
              value={falsifier} onChange={e => setFalsifier(e.target.value)} />
          </div>

          {/* Conviction slider */}
          <div>
            <Label>CONVICTION — <span className="text-cyan">{CONV_LABEL[conviction]} ({conviction}/5)</span></Label>
            <input type="range" min={1} max={5} value={conviction}
              onChange={e => setConviction(Number(e.target.value))}
              className="mt-1 w-full cursor-pointer accent-cyan" />
            <div className="flex justify-between">
              {[1,2,3,4,5].map(v => (
                <span key={v} className={cn('num text-[10px]', v === conviction ? 'text-cyan' : 'text-faint')}>
                  {v}
                </span>
              ))}
            </div>
            <ConvictionNudge conviction={conviction} />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="review">REVIEW DATE</Label>
              <Input id="review" type="date" value={reviewDate}
                onChange={e => setReviewDate(e.target.value)} />
            </div>
            <div>
              <Label htmlFor="entry">ENTRY PRICE (optional)</Label>
              <Input id="entry" type="number" step="0.01" placeholder="—"
                value={entryPrice} onChange={e => setEntryPrice(e.target.value)} />
            </div>
          </div>

          <div>
            <Label htmlFor="reasoning">REASONING (optional)</Label>
            <Textarea id="reasoning" placeholder="What's the core logic?"
              value={reasoning} onChange={e => setReasoning(e.target.value)} className="min-h-16" />
          </div>

          {/* ── Pre-commitment ────────────────────────────── */}
          <Section title="PRE-COMMITMENT (optional — locked at creation)"
            subtitle="These fields cannot be edited after creation. Forces honest reasoning before the outcome is known." />

          <div>
            <Label htmlFor="base_rate">BASE RATE</Label>
            <Textarea id="base_rate"
              placeholder="What's the outside-view reference class? How often do similar situations resolve this way?"
              value={baseRate} onChange={e => setBaseRate(e.target.value)} className="min-h-16" />
          </div>

          <div>
            <Label htmlFor="pre_mortem">PRE-MORTEM</Label>
            <Textarea id="pre_mortem"
              placeholder="Assume this thesis is wrong 12 months from now. What most likely killed it?"
              value={preMortem} onChange={e => setPreMortem(e.target.value)} className="min-h-16" />
          </div>

          <div>
            <Label htmlFor="change_my_mind">WHAT WOULD CHANGE MY MIND</Label>
            <Textarea id="change_my_mind"
              placeholder="What evidence or events, short of the full falsifier, would make you update your conviction down?"
              value={changeMyMind} onChange={e => setChangeMyMind(e.target.value)} className="min-h-16" />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label htmlFor="sizing">SIZING RATIONALE</Label>
              <Textarea id="sizing" placeholder="Why this position size?"
                value={sizingRationale} onChange={e => setSizingRationale(e.target.value)} className="min-h-16" />
            </div>
            <div>
              <Label htmlFor="why_now">WHY NOW</Label>
              <Textarea id="why_now" placeholder="What's the catalyst or timing edge?"
                value={whyNow} onChange={e => setWhyNow(e.target.value)} className="min-h-16" />
            </div>
          </div>

          {/* ── Cooling-off ───────────────────────────────── */}
          <Section title="COOLING-OFF (optional)"
            subtitle="Delays thesis activation to reduce action bias. Thesis is created as PENDING and must be manually activated." />

          <div className="flex items-center gap-4">
            <label className="flex cursor-pointer items-center gap-2">
              <input type="checkbox" checked={coolingOff} onChange={e => setCoolingOff(e.target.checked)}
                className="accent-cyan h-3.5 w-3.5 cursor-pointer" />
              <span className="num text-[11px] text-ink">ENABLE COOLING-OFF PERIOD</span>
            </label>
            {coolingOff && (
              <Select value={coolingHours} onChange={e => setCoolingHours(Number(e.target.value))}
                className="w-40">
                <option value={12}>12 hours</option>
                <option value={24}>24 hours</option>
                <option value={48}>48 hours</option>
                <option value={72}>72 hours</option>
              </Select>
            )}
          </div>

          {/* ── Submit ────────────────────────────────────── */}
          {create.isError && (
            <p className="num text-[11px] text-down">
              FAILED: {create.error instanceof Error ? create.error.message : 'unknown error'}
            </p>
          )}

          <div className="flex items-center justify-between border-t border-border pt-4">
            <p className="font-sans text-[11px] text-faint">
              {coolingOff ? `Will be created as PENDING — activate after ${coolingHours}h cooling-off period.` : 'Will be created as OPEN immediately.'}
            </p>
            <Button type="submit" variant="primary" disabled={!valid || create.isPending}>
              {create.isPending ? 'SAVING…' : coolingOff ? 'CREATE (PENDING)' : 'CREATE THESIS'}
            </Button>
          </div>

        </div>
      </form>
    </div>
  )
}
