import { Loader2 } from 'lucide-react'

import type { ReactNode } from 'react'
import { Card } from './Card'

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 py-12 text-muted">
      <Loader2 className="h-5 w-5 animate-spin" />
      <span>{label}</span>
    </div>
  )
}

export function ErrorState({ error }: { error: unknown }) {
  const msg = error instanceof Error ? error.message : 'Something went wrong.'
  return (
    <Card className="border-down/30 bg-down/[0.06]">
      <p className="font-medium text-down">Failed to load</p>
      <p className="mt-1 text-sm text-muted">{msg}</p>
    </Card>
  )
}

export function EmptyState({
  title,
  children,
}: {
  title: string
  children?: ReactNode
}) {
  return (
    <Card className="flex flex-col items-center py-12 text-center">
      <p className="font-medium text-ink">{title}</p>
      {children && <p className="mt-1 max-w-sm text-sm text-muted">{children}</p>}
    </Card>
  )
}
