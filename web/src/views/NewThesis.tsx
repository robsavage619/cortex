import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { ConvictionMeter } from '@/components/ui/ConvictionMeter'
import { Input, Label, Select, Textarea } from '@/components/ui/Field'
import { useCreateThesis } from '@/lib/api'

export function NewThesis() {
  const navigate = useNavigate()
  const create = useCreateThesis()

  const [tickers, setTickers] = useState('')
  const [author, setAuthor] = useState('rob')
  const [conviction, setConviction] = useState(3)
  const [claim, setClaim] = useState('')
  const [falsifier, setFalsifier] = useState('')
  const [reasoning, setReasoning] = useState('')
  const [reviewDate, setReviewDate] = useState('')
  const [entryPrice, setEntryPrice] = useState('')

  const valid =
    tickers.trim() && claim.trim() && falsifier.trim() && reviewDate

  function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!valid) return
    create.mutate(
      {
        tickers: tickers
          .split(',')
          .map((t) => t.trim().toUpperCase())
          .filter(Boolean),
        author,
        conviction,
        claim: claim.trim(),
        falsifier: falsifier.trim(),
        reasoning: reasoning.trim() || null,
        review_date: reviewDate,
        entry_price: entryPrice ? Number(entryPrice) : null,
      },
      { onSuccess: (t) => navigate(`/thesis/${t.id}`) },
    )
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">New thesis</h1>
        <p className="text-sm text-muted">
          A thesis is a bet. State a falsifiable claim and what would prove it wrong.
        </p>
      </header>

      <Card>
        <form onSubmit={submit} className="space-y-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <Label htmlFor="tickers">Tickers</Label>
              <Input
                id="tickers"
                placeholder="AAPL, MSFT"
                value={tickers}
                onChange={(e) => setTickers(e.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="author">Author</Label>
              <Select id="author" value={author} onChange={(e) => setAuthor(e.target.value)}>
                <option value="rob">rob</option>
                <option value="ari">ari</option>
              </Select>
            </div>
          </div>

          <div>
            <Label htmlFor="claim">Claim</Label>
            <Textarea
              id="claim"
              placeholder="What do you believe will happen, and roughly by when?"
              value={claim}
              onChange={(e) => setClaim(e.target.value)}
            />
          </div>

          <div>
            <Label htmlFor="falsifier">Falsifier</Label>
            <Textarea
              id="falsifier"
              placeholder="What observation would prove this thesis wrong?"
              value={falsifier}
              onChange={(e) => setFalsifier(e.target.value)}
            />
          </div>

          <div>
            <Label htmlFor="reasoning">Reasoning (optional)</Label>
            <Textarea
              id="reasoning"
              value={reasoning}
              onChange={(e) => setReasoning(e.target.value)}
            />
          </div>

          <div>
            <Label>Conviction</Label>
            <div className="flex items-center gap-4">
              <input
                type="range"
                min={1}
                max={5}
                value={conviction}
                onChange={(e) => setConviction(Number(e.target.value))}
                className="flex-1 accent-[#8b5cf6]"
              />
              <ConvictionMeter value={conviction} />
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <Label htmlFor="review">Review date</Label>
              <Input
                id="review"
                type="date"
                value={reviewDate}
                onChange={(e) => setReviewDate(e.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="entry">Entry price (optional)</Label>
              <Input
                id="entry"
                type="number"
                step="0.01"
                placeholder="—"
                value={entryPrice}
                onChange={(e) => setEntryPrice(e.target.value)}
              />
            </div>
          </div>

          {create.isError && (
            <p className="text-sm text-down">
              {create.error instanceof Error ? create.error.message : 'Failed to save.'}
            </p>
          )}

          <div className="flex justify-end gap-3">
            <Button type="button" variant="ghost" onClick={() => navigate(-1)}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" disabled={!valid || create.isPending}>
              {create.isPending ? 'Saving…' : 'Create thesis'}
            </Button>
          </div>
        </form>
      </Card>
    </div>
  )
}
