import { Link } from 'react-router-dom'

import { ThesisCard } from '@/components/ThesisCard'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, Loading } from '@/components/ui/States'
import { StatTile } from '@/components/ui/StatTile'
import { useCalibration, useReviewQueue, useTheses } from '@/lib/api'

export function Dashboard() {
  const theses = useTheses()
  const queue = useReviewQueue()
  const cal = useCalibration()

  if (theses.isLoading) return <Loading label="Loading theses…" />
  if (theses.isError) return <ErrorState error={theses.error} />

  const all = theses.data ?? []
  const open = all.filter((t) => t.status === 'open')
  const reviewed = all.length - open.length

  return (
    <div className="space-y-6">
      <header className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
          <p className="text-sm text-muted">Your household's open theses and decision quality.</p>
        </div>
        <Link to="/new">
          <Button variant="primary">New thesis</Button>
        </Link>
      </header>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatTile label="Open theses" value={open.length} />
        <StatTile label="Reviewed" value={reviewed} />
        <StatTile
          label="Due for review"
          value={queue.data?.length ?? '—'}
          delta={
            queue.data && queue.data.length > 0
              ? { value: 'action', tone: 'down' }
              : undefined
          }
        />
        <StatTile
          label="Brier score"
          value={cal.data ? cal.data.brier_score.toFixed(3) : '—'}
          hint={cal.data?.overconfident ? 'Overconfident' : 'Lower is better'}
        />
      </div>

      <section>
        <h2 className="mb-3 text-sm font-medium uppercase tracking-wide text-muted">
          Open theses ({open.length})
        </h2>
        {open.length === 0 ? (
          <EmptyState title="No open theses yet">
            Frame a falsifiable thesis to start tracking your decision quality.
          </EmptyState>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {open.map((t) => (
              <ThesisCard key={t.id} thesis={t} />
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
