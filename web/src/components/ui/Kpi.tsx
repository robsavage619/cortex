import type { ReactNode } from 'react'

import { Sparkline } from '@/components/charts/Sparkline'
import { AnimatedNumber } from './AnimatedNumber'
import { cn } from '@/lib/utils'

export function Kpi({
  label,
  value,
  animateTo,
  format,
  delta,
  spark,
  accent,
}: {
  label: string
  value?: ReactNode
  animateTo?: number
  format?: (n: number) => string
  delta?: { value: string; tone: 'up' | 'down' | 'neutral' } | null
  spark?: number[]
  accent?: boolean
}) {
  return (
    <div className="glass flex flex-col gap-2 p-4">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-faint">
          {label}
        </span>
        {delta && (
          <span
            className={cn(
              'num rounded-full px-1.5 py-0.5 text-[11px] font-medium',
              delta.tone === 'up' && 'bg-up/15 text-up',
              delta.tone === 'down' && 'bg-down/15 text-down',
              delta.tone === 'neutral' && 'bg-white/[0.06] text-muted',
            )}
          >
            {delta.value}
          </span>
        )}
      </div>
      <div className="flex items-end justify-between gap-2">
        <span
          className={cn(
            'num text-[28px] font-semibold leading-none',
            accent ? 'accent-text' : 'text-ink',
          )}
        >
          {animateTo != null ? (
            <AnimatedNumber value={animateTo} format={format} />
          ) : (
            value
          )}
        </span>
        {spark && spark.length > 1 && <Sparkline values={spark} width={72} height={26} />}
      </div>
    </div>
  )
}
