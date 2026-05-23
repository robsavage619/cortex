import { cn } from '@/lib/utils'

export function ConvictionMeter({
  value,
  className,
}: {
  value: number
  className?: string
}) {
  return (
    <div className={cn('flex items-center gap-1', className)} title={`Conviction ${value}/5`}>
      {[1, 2, 3, 4, 5].map((n) => (
        <span
          key={n}
          className={cn(
            'h-1.5 w-5 rounded-full',
            n <= value ? 'accent-gradient' : 'bg-hairline',
          )}
        />
      ))}
      <span className="tabular ml-2 text-xs text-muted">{value}/5</span>
    </div>
  )
}
