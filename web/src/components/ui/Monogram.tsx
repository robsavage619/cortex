import { useState } from 'react'

import { cn } from '@/lib/utils'

const TOKEN = import.meta.env.VITE_LOGODEV_TOKEN as string | undefined

const sizes = {
  sm: 'h-8 w-8 text-xs',
  md: 'h-10 w-10 text-sm',
  lg: 'h-14 w-14 text-lg',
}

/**
 * Real ticker logo via logo.dev's free tier, with a gradient monogram fallback.
 * The monogram renders instantly and carries the look if logo.dev is unset or fails,
 * so the portal never depends on the external service.
 */
export function Monogram({
  ticker,
  size = 'md',
  className,
}: {
  ticker: string
  size?: keyof typeof sizes
  className?: string
}) {
  const [failed, setFailed] = useState(false)
  const letters = ticker.slice(0, 2).toUpperCase()
  const showLogo = Boolean(TOKEN) && !failed

  return (
    <div
      className={cn(
        'flex shrink-0 items-center justify-center overflow-hidden rounded-2xl font-semibold text-white',
        !showLogo && 'accent-gradient',
        sizes[size],
        className,
      )}
    >
      {showLogo ? (
        <img
          src={`https://img.logo.dev/ticker/${ticker}?token=${TOKEN}&format=png&size=80`}
          alt={ticker}
          className="h-full w-full object-cover"
          onError={() => setFailed(true)}
        />
      ) : (
        letters
      )}
    </div>
  )
}
