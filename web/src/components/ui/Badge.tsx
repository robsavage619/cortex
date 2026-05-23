import { cn } from '@/lib/utils'
import type { ThesisStatus } from '@/lib/types'

const statusStyles: Record<ThesisStatus, string> = {
  open: 'bg-accent/15 text-[#a5b4fc]',
  confirmed: 'bg-up/15 text-up',
  invalidated: 'bg-down/15 text-down',
  closed: 'bg-white/[0.06] text-muted',
}

export function StatusBadge({ status }: { status: ThesisStatus }) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize',
        statusStyles[status],
      )}
    >
      {status}
    </span>
  )
}

export function Pill({
  children,
  tone = 'muted',
}: {
  children: React.ReactNode
  tone?: 'muted' | 'up' | 'down' | 'warn'
}) {
  const tones = {
    muted: 'bg-white/[0.06] text-muted',
    up: 'bg-up/15 text-up',
    down: 'bg-down/15 text-down',
    warn: 'bg-warn/15 text-warn',
  }
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium',
        tones[tone],
      )}
    >
      {children}
    </span>
  )
}
