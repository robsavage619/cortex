import { useState } from 'react'

import { cn } from '@/lib/utils'

export function TickerLogo({
  ticker,
  website: _website,
  size = 28,
  className,
}: {
  ticker: string
  website?: string | null
  size?: number
  className?: string
}) {
  const [errored, setErrored] = useState(false)
  const src = `https://assets.parqet.com/logos/symbol/${ticker}`

  if (errored) {
    return (
      <div
        style={{ width: size, height: size }}
        className={cn(
          'flex shrink-0 items-center justify-center rounded-sm border border-border bg-bg-hover font-mono text-[10px] font-bold text-faint',
          className,
        )}
      >
        {ticker.slice(0, 2)}
      </div>
    )
  }

  return (
    <img
      src={src}
      alt={ticker}
      width={size}
      height={size}
      className={cn('shrink-0 rounded-sm object-contain', className)}
      onError={() => setErrored(true)}
    />
  )
}
