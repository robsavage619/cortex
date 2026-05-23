import { ArrowLeft } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { Pill, StatusBadge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card, CardTitle } from '@/components/ui/Card'
import { ConvictionMeter } from '@/components/ui/ConvictionMeter'
import { Textarea } from '@/components/ui/Field'
import { Monogram } from '@/components/ui/Monogram'
import { ErrorState, Loading } from '@/components/ui/States'
import {
  useContext,
  usePatchThesis,
  useRecordReview,
  useThesis,
} from '@/lib/api'
import type { ReviewOutcome } from '@/lib/types'
import { fmtCompact, fmtDate, fmtPrice, fmtSignedPercent } from '@/lib/utils'

export function ThesisDetail() {
  const { id = '' } = useParams()
  const thesis = useThesis(id)
  const patch = usePatchThesis(id)
  const review = useRecordReview(id)
  const [note, setNote] = useState('')

  const firstTicker = thesis.data?.tickers[0] ?? null
  const ctx = useContext(firstTicker)

  if (thesis.isLoading) return <Loading label="Loading thesis…" />
  if (thesis.isError) return <ErrorState error={thesis.error} />
  const t = thesis.data!
  const open = t.status === 'open'

  function grade(outcome: ReviewOutcome) {
    review.mutate(
      { outcome, note: note.trim() || null },
      { onSuccess: () => setNote('') },
    )
  }

  return (
    <div className="space-y-6">
      <Link to="/" className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink">
        <ArrowLeft className="h-4 w-4" /> Back
      </Link>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Card>
            <div className="flex items-start gap-3">
              <div className="flex -space-x-2">
                {t.tickers.map((tk) => (
                  <Monogram key={tk} ticker={tk} className="ring-2 ring-bg" />
                ))}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="tabular text-lg font-semibold">{t.tickers.join(', ')}</span>
                  <StatusBadge status={t.status} />
                </div>
                <p className="text-xs text-faint">
                  by {t.author} · opened {fmtDate(t.opened)}
                </p>
              </div>
              <ConvictionMeter value={t.conviction} />
            </div>

            <h1 className="mt-5 text-xl font-semibold leading-snug">{t.claim}</h1>

            <div className="mt-5 space-y-4 text-sm">
              <Field label="Falsifier" tone="down">
                {t.falsifier}
              </Field>
              {t.reasoning && <Field label="Reasoning">{t.reasoning}</Field>}
              <div className="grid grid-cols-2 gap-4">
                <Field label="Review date">{fmtDate(t.review_date)}</Field>
                <Field label="Entry price">{fmtPrice(t.entry_price)}</Field>
              </div>
              {t.evidence.length > 0 && (
                <Field label="Evidence">
                  <div className="flex flex-wrap gap-2">
                    {t.evidence.map((e) => (
                      <Pill key={e}>{e}</Pill>
                    ))}
                  </div>
                </Field>
              )}
            </div>
          </Card>

          {open && (
            <Card>
              <CardTitle className="mb-1">Review this thesis</CardTitle>
              <p className="mb-4 text-sm text-muted">
                Grade the outcome honestly. This feeds your calibration score.
              </p>
              <Textarea
                placeholder="Optional note on what happened…"
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
              <div className="mt-4 flex flex-wrap gap-3">
                <Button
                  variant="primary"
                  disabled={review.isPending}
                  onClick={() => grade('correct')}
                >
                  Correct
                </Button>
                <Button
                  variant="danger"
                  disabled={review.isPending}
                  onClick={() => grade('wrong')}
                >
                  Wrong
                </Button>
                <Button disabled={review.isPending} onClick={() => grade('unclear')}>
                  Unclear
                </Button>
                <Button
                  variant="ghost"
                  disabled={patch.isPending}
                  onClick={() => patch.mutate({ status: 'closed' })}
                >
                  Close without grading
                </Button>
              </div>
              {review.isError && (
                <p className="mt-3 text-sm text-down">Failed to record review.</p>
              )}
            </Card>
          )}
        </div>

        <div className="space-y-6">
          <Card>
            <CardTitle className="mb-4">
              Context{firstTicker ? ` · ${firstTicker}` : ''}
            </CardTitle>
            {ctx.isLoading && <p className="text-sm text-muted">Fetching live context…</p>}
            {ctx.data?.market && (
              <div className="space-y-3">
                <Row label="Price" value={fmtPrice(ctx.data.market.price)} />
                <Row
                  label="Day change"
                  value={fmtSignedPercent(ctx.data.market.day_change_percent)}
                  tone={
                    (ctx.data.market.day_change_percent ?? 0) >= 0 ? 'up' : 'down'
                  }
                />
                <Row label="52w high" value={fmtPrice(ctx.data.market.week_52_high)} />
                <Row label="52w low" value={fmtPrice(ctx.data.market.week_52_low)} />
                <Row label="Market cap" value={fmtCompact(ctx.data.market.market_cap)} />
                <Row
                  label="P/E"
                  value={ctx.data.market.pe_ratio?.toFixed(1) ?? '—'}
                />
              </div>
            )}
            {ctx.data?.market_error && (
              <p className="text-sm text-warn">Market data unavailable: {ctx.data.market_error}</p>
            )}
            <p className="mt-4 text-xs text-faint">
              Neutral context for grading — never a recommendation.
            </p>
          </Card>

          {ctx.data?.senate_trades && ctx.data.senate_trades.length > 0 && (
            <Card>
              <CardTitle className="mb-3">Recent Senate trades</CardTitle>
              <div className="space-y-2 text-sm">
                {ctx.data.senate_trades.map((tr, i) => (
                  <div key={i} className="flex items-center justify-between gap-2">
                    <span className="min-w-0 truncate text-ink">{tr.senator}</span>
                    <Pill tone={tr.transaction_type.toLowerCase().includes('purchase') ? 'up' : 'down'}>
                      {tr.transaction_type}
                    </Pill>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}

function Field({
  label,
  tone,
  children,
}: {
  label: string
  tone?: 'down'
  children: React.ReactNode
}) {
  return (
    <div>
      <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted">{label}</p>
      <div className={tone === 'down' ? 'text-down' : 'text-ink'}>{children}</div>
    </div>
  )
}

function Row({
  label,
  value,
  tone,
}: {
  label: string
  value: string
  tone?: 'up' | 'down'
}) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-sm text-muted">{label}</span>
      <span
        className={`tabular text-sm ${
          tone === 'up' ? 'text-up' : tone === 'down' ? 'text-down' : 'text-ink'
        }`}
      >
        {value}
      </span>
    </div>
  )
}
