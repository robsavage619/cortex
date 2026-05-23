import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'
import { Card } from './Card'

export function StatTile({
  label,
  value,
  delta,
  hint,
}: {
  label: string
  value: ReactNode
  delta?: { value: string; tone: 'up' | 'down' | 'neutral' }
  hint?: string
}) {
  return (
    <Card className="p-5">
      <p className="text-sm font-medium text-muted">{label}</p>
      <div className="mt-2 flex items-end justify-between gap-2">
        <span className="tabular text-3xl font-semibold text-ink">{value}</span>
        {delta && (
          <span
            className={cn(
              'tabular rounded-full px-2 py-0.5 text-xs font-medium',
              delta.tone === 'up' && 'bg-up/15 text-up',
              delta.tone === 'down' && 'bg-down/15 text-down',
              delta.tone === 'neutral' && 'bg-white/[0.06] text-muted',
            )}
          >
            {delta.value}
          </span>
        )}
      </div>
      {hint && <p className="mt-1 text-xs text-faint">{hint}</p>}
    </Card>
  )
}
