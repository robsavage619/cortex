import { ThesisCard } from '@/components/ThesisCard'
import { EmptyState, ErrorState, Loading } from '@/components/ui/States'
import { useReviewQueue } from '@/lib/api'

export function ReviewQueue() {
  const queue = useReviewQueue()

  if (queue.isLoading) return <Loading label="Loading review queue…" />
  if (queue.isError) return <ErrorState error={queue.error} />

  const due = queue.data ?? []

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Review queue</h1>
        <p className="text-sm text-muted">
          Open theses past their review date. Grade them honestly — that's the calibration loop.
        </p>
      </header>

      {due.length === 0 ? (
        <EmptyState title="Nothing due">
          No open theses have reached their review date. Low frequency is the point.
        </EmptyState>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {due.map((t) => (
            <ThesisCard key={t.id} thesis={t} />
          ))}
        </div>
      )}
    </div>
  )
}
