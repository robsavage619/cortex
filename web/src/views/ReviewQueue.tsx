import { useState } from 'react'
import { Link } from 'react-router-dom'

import { Button } from '@/components/ui/Button'
import { Select } from '@/components/ui/Field'
import { useRecordReview, useReviewQueue } from '@/lib/api'
import type { DecisionQuality, ReviewOutcome, Thesis } from '@/lib/types'
import { cn, daysUntil, fmtDate, fmtPrice } from '@/lib/utils'

// ── Inline review row ─────────────────────────────────────────────────────────

function ReviewRow({ t }: { t: Thesis }) {
  const [outcome,  setOutcome]  = useState<ReviewOutcome>('correct')
  const [quality,  setQuality]  = useState<DecisionQuality>('good')
  const [expanded, setExpanded] = useState(false)
  const review = useRecordReview(t.id)
  const days   = daysUntil(t.review_date)
  const overdue = days < 0

  function submit() {
    review.mutate(
      { outcome, decision_quality: quality },
      { onSuccess: () => setExpanded(false) },
    )
  }

  return (
    <>
      <tr
        className={cn(
          'group border-b border-border-dim cursor-pointer transition-colors hover:bg-bg-hover',
          expanded && 'bg-bg-selected',
        )}
        onClick={() => setExpanded(v => !v)}
      >
        {/* Status dot */}
        <td className="w-5 px-2 py-2 text-center">
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-warn" />
        </td>

        {/* Ticker */}
        <td className="w-20 px-3 py-2">
          <span className="num text-[12px] font-bold text-ink">{t.tickers.join(' ')}</span>
        </td>

        {/* Claim */}
        <td className="px-3 py-2">
          <span className="block truncate font-sans text-[13px] text-ink">{t.claim}</span>
          <span className="block truncate font-sans text-[11px] text-muted">⚡ {t.falsifier}</span>
        </td>

        {/* Conv */}
        <td className="w-16 px-3 py-2">
          <span className="num text-[12px] text-muted">{t.conviction}/5</span>
        </td>

        {/* Entry */}
        <td className="w-28 px-3 py-2">
          <span className="num text-[12px] text-muted">{fmtPrice(t.entry_price)}</span>
        </td>

        {/* Review date */}
        <td className="w-36 px-3 py-2">
          <span className="num block text-[11px] text-muted">{fmtDate(t.review_date)}</span>
          <span className={cn('num block text-[10px] font-semibold', overdue ? 'text-down' : 'text-warn')}>
            {overdue ? `${Math.abs(days)}d OVERDUE` : 'DUE TODAY'}
          </span>
        </td>

        {/* Action hint */}
        <td className="w-24 px-3 py-2 text-right">
          <span className="num text-[10px] text-muted">
            {expanded ? 'COLLAPSE ↑' : 'GRADE ↓'}
          </span>
        </td>
      </tr>

      {/* Inline grade panel */}
      {expanded && (
        <tr className="border-b border-border bg-bg-selected">
          <td colSpan={7} className="px-5 py-4">
            <div className="flex items-end gap-4 flex-wrap">
              <div className="flex flex-col gap-1">
                <span className="label">OUTCOME</span>
                <Select
                  value={outcome}
                  onChange={e => setOutcome(e.target.value as ReviewOutcome)}
                  className="w-40"
                >
                  <option value="correct">correct</option>
                  <option value="wrong">wrong</option>
                  <option value="unclear">unclear</option>
                </Select>
              </div>
              <div className="flex flex-col gap-1">
                <span className="label">DECISION QUALITY</span>
                <Select
                  value={quality}
                  onChange={e => setQuality(e.target.value as DecisionQuality)}
                  className="w-44"
                >
                  <option value="good">good process</option>
                  <option value="flawed">flawed process</option>
                  <option value="unknown">unknown</option>
                </Select>
              </div>
              <div className="flex gap-2">
                <Button variant="primary" onClick={submit} disabled={review.isPending}>
                  {review.isPending ? 'SAVING…' : 'RECORD'}
                </Button>
                <Link to={`/thesis/${t.id}`}>
                  <Button>OPEN FULL</Button>
                </Link>
              </div>
              {review.isError && (
                <span className="num text-[11px] text-down">FAILED — retry</span>
              )}
            </div>
            <p className="font-sans mt-3 text-[11px] text-faint">
              Grade outcome separately from process quality. Correct outcome + flawed process = lucky, not skilled.
            </p>
          </td>
        </tr>
      )}
    </>
  )
}

// ── Review Queue ──────────────────────────────────────────────────────────────

export function ReviewQueue() {
  const queue = useReviewQueue()
  const due   = queue.data ?? []

  if (queue.isLoading) {
    return <div className="flex flex-1 items-center justify-center">
      <span className="num text-sm text-muted">LOADING REVIEW QUEUE…</span>
    </div>
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">

      {/* Header bar */}
      <div className="flex shrink-0 items-center justify-between border-b border-border bg-bg-panel px-5 py-3">
        <div>
          <span className="num text-sm font-semibold text-ink">REVIEW QUEUE</span>
          <span className="num ml-3 text-[11px] text-faint">
            {due.length} {due.length === 1 ? 'THESIS' : 'THESES'} DUE
          </span>
        </div>
        {due.length > 0 && (
          <span className="num text-[11px] text-warn">⚠ ACTION NEEDED</span>
        )}
      </div>

      {due.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3">
          <span className="num text-sm text-up">✓ ALL CLEAR</span>
          <p className="font-sans text-[12px] text-faint max-w-sm text-center">
            No open theses have reached their review date. Low review frequency is by design — it reduces action bias.
          </p>
          <Link to="/" className="num mt-2 text-[11px] text-muted hover:text-cyan">
            ← BACK TO DASHBOARD
          </Link>
        </div>
      ) : (
        <div className="flex-1 overflow-auto">
          <table className="w-full min-w-[700px]">
            <colgroup>
              <col className="w-5" />
              <col className="w-20" />
              <col />
              <col className="w-16" />
              <col className="w-28" />
              <col className="w-36" />
              <col className="w-24" />
            </colgroup>
            <thead className="sticky top-0 z-10 bg-bg-panel">
              <tr>
                <th className="w-5 border-b border-border" />
                <th className="label w-20 border-b border-border px-3 py-2 text-left">TICKER</th>
                <th className="label border-b border-border px-3 py-2 text-left">THESIS</th>
                <th className="label w-16 border-b border-border px-3 py-2 text-left">CONV</th>
                <th className="label w-28 border-b border-border px-3 py-2 text-left">ENTRY</th>
                <th className="label w-36 border-b border-border px-3 py-2 text-left">REVIEW DATE</th>
                <th className="w-24 border-b border-border" />
              </tr>
            </thead>
            <tbody>
              {due.map(t => <ReviewRow key={t.id} t={t} />)}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
