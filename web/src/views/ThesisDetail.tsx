import { MessageSquare } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { PriceChart } from '@/components/charts/PriceChart'
import { Pill } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Label, Select, Textarea } from '@/components/ui/Field'
import {
  useActivate,
  useAddDissent,
  useHistory,
  useRecordReview,
  useThesis,
  useTickerContext,
} from '@/lib/api'
import type { DecisionQuality, ReviewOutcome, Stance } from '@/lib/types'
import { cn, daysUntil, fmtDate, fmtPrice, fmtSignedPercent } from '@/lib/utils'

// ── Helpers ───────────────────────────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="border-b border-border px-5 py-2">
      <span className="label">{children}</span>
    </div>
  )
}

function DataRow({ label, value, tone, mono = true }: {
  label: string; value: React.ReactNode
  tone?: 'up' | 'down' | 'warn' | 'muted'; mono?: boolean
}) {
  const colors = { up: 'text-up', down: 'text-down', warn: 'text-warn', muted: 'text-muted' }
  return (
    <div className="flex items-center justify-between gap-4 border-b border-border-dim px-5 py-2 last:border-b-0">
      <span className="label shrink-0">{label}</span>
      <span className={cn(mono ? 'num' : 'font-sans', 'text-[12px] text-right', tone ? colors[tone] : 'text-ink')}>
        {value}
      </span>
    </div>
  )
}

function PreCommitField({ label, value }: { label: string; value: string | null }) {
  if (!value) return null
  return (
    <div className="border-b border-border-dim px-5 py-3 last:border-b-0">
      <span className="label block mb-1">{label}</span>
      <p className="font-sans text-[12px] text-muted leading-relaxed">{value}</p>
    </div>
  )
}

// ── Status helpers ────────────────────────────────────────────────────────────

const STATUS_COLOR: Record<string, string> = {
  open: 'text-open', pending: 'text-warn', confirmed: 'text-up',
  invalidated: 'text-down', closed: 'text-muted',
}

// ── Main view ─────────────────────────────────────────────────────────────────

export function ThesisDetail() {
  const { id = '' } = useParams()
  const thesis    = useThesis(id)
  const review    = useRecordReview(id)
  const activate  = useActivate(id)
  const addDissent = useAddDissent(id)

  const [outcome,  setOutcome]  = useState<ReviewOutcome>('correct')
  const [quality,  setQuality]  = useState<DecisionQuality>('good')
  const [note,     setNote]     = useState('')
  const [dissentAuthor, setDissentAuthor] = useState('rob')
  const [dissentStance, setDissentStance] = useState<Stance>('disagree')
  const [dissentNote,   setDissentNote]   = useState('')
  const [showDissent,   setShowDissent]   = useState(false)

  const t        = thesis.data
  const lead     = t?.tickers[0] ?? null
  const ctx      = useTickerContext(lead)
  const { data: bars } = useHistory(lead, '1y')
  const price    = ctx.data?.market?.price ?? null
  const change   = ctx.data?.market?.day_change_percent ?? null

  if (thesis.isLoading) {
    return <div className="flex flex-1 items-center justify-center">
      <span className="num text-sm text-muted">LOADING…</span>
    </div>
  }
  if (!t) return <div className="flex flex-1 items-center justify-center">
    <span className="num text-sm text-down">THESIS NOT FOUND</span>
  </div>

  const open    = t.status === 'open'
  const pending = t.status === 'pending'
  const days    = daysUntil(t.review_date)
  const pnl     = t.entry_price && price ? ((price - t.entry_price) / t.entry_price) * 100 : null
  const hasPreCommit = t.base_rate || t.pre_mortem || t.change_my_mind || t.sizing_rationale || t.why_now

  function submitReview() {
    review.mutate(
      { outcome, decision_quality: quality, note: note.trim() || null },
      { onSuccess: () => setNote('') },
    )
  }

  function submitDissent() {
    addDissent.mutate(
      { author: dissentAuthor, stance: dissentStance, note: dissentNote.trim() || null },
      { onSuccess: () => { setDissentNote(''); setShowDissent(false) } },
    )
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">

      {/* ── Top bar ─────────────────────────────────────── */}
      <div className="flex shrink-0 items-center gap-4 border-b border-border bg-bg-panel px-5 py-2">
        <Link to="/" className="num text-[10px] tracking-widest text-muted hover:text-cyan">
          ← DASHBOARD
        </Link>
        <span className="text-border">|</span>
        <span className="num text-sm font-bold text-ink">{t.tickers.join(' / ')}</span>
        {price != null && (
          <span className={cn('num text-sm', (change ?? 0) >= 0 ? 'text-up' : 'text-down')}>
            {fmtPrice(price)} {fmtSignedPercent(change)}
          </span>
        )}
        {pnl != null && (
          <span className={cn('num text-[11px]', pnl >= 0 ? 'text-up' : 'text-down')}>
            vs entry {pnl >= 0 ? '+' : ''}{pnl.toFixed(1)}%
          </span>
        )}
        <span className={cn('num ml-auto text-[11px] font-semibold tracking-widest', STATUS_COLOR[t.status])}>
          {t.status.toUpperCase()}
        </span>
        {pending && (
          <Button variant="primary" onClick={() => activate.mutate()} disabled={activate.isPending}>
            ACTIVATE
          </Button>
        )}
      </div>

      {/* ── Body: left content + right panel ────────────── */}
      <div className="flex flex-1 overflow-hidden">

        {/* Left: chart + thesis body */}
        <div className="flex flex-1 flex-col overflow-y-auto min-w-0">

          {/* Price chart */}
          <div className="border-b border-border">
            <PriceChart bars={bars ?? []} entryPrice={t.entry_price} height={260} />
          </div>

          {/* Thesis text */}
          <div className="border-b border-border">
            <SectionLabel>THESIS</SectionLabel>
            <div className="px-5 py-4">
              <p className="font-sans text-[14px] text-ink leading-relaxed">{t.claim}</p>
            </div>
          </div>

          <div className="border-b border-border">
            <SectionLabel>INVALIDATED IF</SectionLabel>
            <div className="px-5 py-4">
              <p className="font-sans text-[13px] text-down leading-relaxed">⚡ {t.falsifier}</p>
            </div>
          </div>

          {t.reasoning && (
            <div className="border-b border-border">
              <SectionLabel>REASONING</SectionLabel>
              <div className="px-5 py-4">
                <p className="font-sans text-[13px] text-muted leading-relaxed">{t.reasoning}</p>
              </div>
            </div>
          )}

          {/* Pre-commitment fields (locked at creation) */}
          {hasPreCommit && (
            <div className="border-b border-border">
              <SectionLabel>PRE-COMMITMENT (LOCKED)</SectionLabel>
              <PreCommitField label="BASE RATE"        value={t.base_rate} />
              <PreCommitField label="PRE-MORTEM"       value={t.pre_mortem} />
              <PreCommitField label="CHANGE MY MIND"   value={t.change_my_mind} />
              <PreCommitField label="SIZING RATIONALE" value={t.sizing_rationale} />
              <PreCommitField label="WHY NOW"          value={t.why_now} />
            </div>
          )}

          {/* Evidence */}
          {t.evidence.length > 0 && (
            <div className="border-b border-border">
              <SectionLabel>EVIDENCE</SectionLabel>
              <div className="flex flex-wrap gap-2 px-5 py-3">
                {t.evidence.map(e => <Pill key={e} tone="cyan">{e}</Pill>)}
              </div>
            </div>
          )}

          {/* Dissent ledger */}
          <div className="border-b border-border">
            <div className="flex items-center justify-between border-b border-border px-5 py-2">
              <span className="label">DISSENTS ({t.dissents?.length ?? 0})</span>
              <button
                onClick={() => setShowDissent(v => !v)}
                className="num text-[10px] tracking-widest text-muted hover:text-cyan"
              >
                + ADD DISSENT
              </button>
            </div>

            {showDissent && (
              <div className="border-b border-border px-5 py-4 space-y-3 bg-bg-row">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <Label>AUTHOR</Label>
                    <Select value={dissentAuthor} onChange={e => setDissentAuthor(e.target.value)}>
                      <option value="rob">rob</option>
                      <option value="ari">ari</option>
                    </Select>
                  </div>
                  <div>
                    <Label>STANCE</Label>
                    <Select value={dissentStance} onChange={e => setDissentStance(e.target.value as Stance)}>
                      <option value="agree">agree</option>
                      <option value="disagree">disagree</option>
                    </Select>
                  </div>
                </div>
                <div>
                  <Label>NOTE (optional)</Label>
                  <Textarea
                    placeholder="What's your take?"
                    value={dissentNote}
                    onChange={e => setDissentNote(e.target.value)}
                    className="min-h-16"
                  />
                </div>
                <div className="flex gap-2">
                  <Button variant="primary" onClick={submitDissent} disabled={addDissent.isPending}>
                    RECORD DISSENT
                  </Button>
                  <Button onClick={() => setShowDissent(false)}>CANCEL</Button>
                </div>
              </div>
            )}

            {(t.dissents ?? []).length === 0 && !showDissent ? (
              <div className="px-5 py-4">
                <p className="font-sans text-[12px] text-faint">No dissents recorded. Use the dissent ledger to track disagreements between authors.</p>
              </div>
            ) : (
              (t.dissents ?? []).map(d => (
                <div key={d.id} className="flex items-start gap-3 border-b border-border-dim px-5 py-3 last:border-b-0">
                  <MessageSquare className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted" />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="num text-[11px] font-semibold text-ink">{d.author.toUpperCase()}</span>
                      <span className={cn('num text-[10px] font-semibold tracking-wide',
                        d.stance === 'agree' ? 'text-up' : 'text-down')}>
                        {d.stance.toUpperCase()}
                      </span>
                      <span className="num text-[10px] text-faint">{fmtDate(d.created_at)}</span>
                    </div>
                    {d.note && <p className="font-sans text-[12px] text-muted">{d.note}</p>}
                  </div>
                </div>
              ))
            )}
          </div>

          {/* Review panel */}
          {(open || pending) && (
            <div className="border-b border-border">
              <SectionLabel>RECORD REVIEW</SectionLabel>
              <div className="px-5 py-4 space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <Label>OUTCOME</Label>
                    <Select value={outcome} onChange={e => setOutcome(e.target.value as ReviewOutcome)}>
                      <option value="correct">correct</option>
                      <option value="wrong">wrong</option>
                      <option value="unclear">unclear</option>
                    </Select>
                  </div>
                  <div>
                    <Label>DECISION QUALITY</Label>
                    <Select value={quality} onChange={e => setQuality(e.target.value as DecisionQuality)}>
                      <option value="good">good process</option>
                      <option value="flawed">flawed process</option>
                      <option value="unknown">unknown</option>
                    </Select>
                  </div>
                </div>
                <div>
                  <Label>NOTE (optional)</Label>
                  <Textarea
                    placeholder="What happened? What did you miss? What would you do differently?"
                    value={note}
                    onChange={e => setNote(e.target.value)}
                    className="min-h-20"
                  />
                </div>
                {review.isError && (
                  <p className="num text-[11px] text-down">FAILED TO RECORD — {String(review.error)}</p>
                )}
                <div className="flex gap-2">
                  <Button variant="primary" onClick={submitReview} disabled={review.isPending}>
                    {review.isPending ? 'SAVING…' : 'RECORD REVIEW'}
                  </Button>
                </div>
                <p className="font-sans text-[11px] text-faint">
                  Decision quality is graded independently of outcome — the core anti-resulting principle.
                  A good process can produce a bad outcome. A flawed process can get lucky.
                </p>
              </div>
            </div>
          )}

        </div>

        {/* Right: context panel */}
        <div className="w-[260px] shrink-0 overflow-y-auto border-l border-border bg-bg-panel">
          <SectionLabel>POSITION</SectionLabel>
          <DataRow label="AUTHOR"    value={t.author.toUpperCase()} />
          <DataRow label="OPENED"    value={fmtDate(t.opened)} />
          <DataRow label="CONVICTION" value={`${t.conviction}/5`} />
          <DataRow label="ENTRY"     value={fmtPrice(t.entry_price)} />
          <DataRow label="REVIEW"    value={fmtDate(t.review_date)} />
          <DataRow label="DAYS"
            value={days < 0 ? `${Math.abs(days)}d overdue` : `${days}d remaining`}
            tone={days < 0 ? 'down' : days <= 7 ? 'warn' : 'muted'} />

          {ctx.data?.market && (
            <>
              <SectionLabel>MARKET</SectionLabel>
              <DataRow label="PRICE"    value={fmtPrice(ctx.data.market.price)}
                tone={(ctx.data.market.day_change_percent ?? 0) >= 0 ? 'up' : 'down'} />
              <DataRow label="DAY Δ"   value={fmtSignedPercent(ctx.data.market.day_change_percent)}
                tone={(ctx.data.market.day_change_percent ?? 0) >= 0 ? 'up' : 'down'} />
              {pnl != null && (
                <DataRow label="vs ENTRY" value={`${pnl >= 0 ? '+' : ''}${pnl.toFixed(1)}%`}
                  tone={pnl >= 0 ? 'up' : 'down'} />
              )}
              <DataRow label="52W HIGH" value={fmtPrice(ctx.data.market.week_52_high)} />
              <DataRow label="52W LOW"  value={fmtPrice(ctx.data.market.week_52_low)} />
              {ctx.data.market.pe_ratio != null && (
                <DataRow label="P/E" value={`${ctx.data.market.pe_ratio.toFixed(1)}×`} />
              )}
              {ctx.data.market.market_cap != null && (
                <DataRow label="MKTCAP" value={`$${(ctx.data.market.market_cap / 1e9).toFixed(0)}B`} />
              )}
            </>
          )}

          {ctx.data?.senate_trades && ctx.data.senate_trades.length > 0 && (
            <>
              <SectionLabel>SENATE TRADES</SectionLabel>
              {ctx.data.senate_trades.slice(0, 5).map((tr, i) => (
                <div key={i} className="border-b border-border-dim px-5 py-2 last:border-b-0">
                  <span className="block truncate font-sans text-[11px] text-ink">{tr.senator}</span>
                  <span className={cn('num text-[10px]',
                    tr.transaction_type.toLowerCase().includes('purchase') ? 'text-up' : 'text-down')}>
                    {tr.transaction_type} · {tr.transaction_date ?? '—'}
                  </span>
                </div>
              ))}
            </>
          )}

          {ctx.data?.market?.news_headlines && ctx.data.market.news_headlines.length > 0 && (
            <>
              <SectionLabel>NEWS</SectionLabel>
              {ctx.data.market.news_headlines.slice(0, 5).map((h, i) => (
                <div key={i} className="border-b border-border-dim px-5 py-2 last:border-b-0">
                  <p className="font-sans text-[11px] text-muted leading-snug">• {h}</p>
                </div>
              ))}
            </>
          )}

          <div className="px-5 py-3">
            <p className="font-sans text-[10px] text-faint leading-relaxed">
              Market data is neutral context for grading — not a recommendation.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
