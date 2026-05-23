import { TrendingDown, TrendingUp } from 'lucide-react'

import { useTickerContext as useContext } from '@/lib/api'
import { cn, fmtPrice, fmtSignedPercent } from '@/lib/utils'

function TickerCell({ ticker }: { ticker: string }) {
  const { data, isLoading } = useContext(ticker)
  const change = data?.market?.day_change_percent ?? null
  const up = (change ?? 0) >= 0

  return (
    <div className="flex shrink-0 items-center gap-2.5 border-r border-hairline px-4 py-2 last:border-r-0">
      <span className="tabular text-sm font-semibold text-ink">{ticker}</span>
      {isLoading ? (
        <span className="text-xs text-faint">…</span>
      ) : (
        <>
          <span className="tabular text-sm text-muted">{fmtPrice(data?.market?.price)}</span>
          <span
            className={cn(
              'tabular inline-flex items-center gap-0.5 text-xs font-medium',
              up ? 'text-up' : 'text-down',
            )}
          >
            {up ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
            {fmtSignedPercent(change)}
          </span>
        </>
      )}
    </div>
  )
}

export function TickerTape({ tickers }: { tickers: string[] }) {
  if (tickers.length === 0) return null
  return (
    <div className="glass flex items-center overflow-x-auto rounded-2xl">
      {tickers.map((t) => (
        <TickerCell key={t} ticker={t} />
      ))}
    </div>
  )
}
