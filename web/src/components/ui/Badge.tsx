import { cn } from '@/lib/utils'
import type { ThesisStatus } from '@/lib/types'

const statusStyles: Record<ThesisStatus, string> = {
  open:        'text-open  bg-open/10',
  pending:     'text-warn  bg-warn/10',
  confirmed:   'text-up    bg-up/10',
  invalidated: 'text-down  bg-down/10',
  closed:      'text-muted bg-white/[0.04]',
}

export function StatusBadge({ status }: { status: ThesisStatus }) {
  return (
    <span
      className={cn(
        'num inline-flex items-center px-1.5 py-0.5 text-[10px] font-semibold tracking-[0.1em] uppercase',
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
  tone?: 'muted' | 'up' | 'down' | 'warn' | 'cyan'
}) {
  const tones = {
    muted: 'bg-white/[0.05] text-muted',
    up:    'bg-up/10 text-up',
    down:  'bg-down/10 text-down',
    warn:  'bg-warn/10 text-warn',
    cyan:  'bg-cyan/10 text-cyan',
  }
  return (
    <span
      className={cn(
        'num inline-flex items-center px-1.5 py-0.5 text-[10px] font-semibold tracking-[0.08em] uppercase',
        tones[tone],
      )}
    >
      {children}
    </span>
  )
}
