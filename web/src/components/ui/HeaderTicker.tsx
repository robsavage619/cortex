import { TrendingDown, TrendingUp } from 'lucide-react'

import { useTheses, useTickerContext } from '@/lib/api'
import { cn, fmtPrice, fmtSignedPercent } from '@/lib/utils'

function TickerChip({ ticker }: { ticker: string }) {
  const { data, isLoading } = useTickerContext(ticker)
  const price = data?.market?.price ?? null
  const change = data?.market?.day_change_percent ?? null
  const up = (change ?? 0) >= 0

  return (
    <div className="flex shrink-0 items-center gap-1.5 border-r border-border px-4 h-full">
      <span className="text-[10px] font-bold tracking-wider text-muted">{ticker}</span>
      {isLoading ? (
        <span className="text-[10px] text-faint">…</span>
      ) : (
        <>
          <span className="tabular text-[10px] text-ink">{fmtPrice(price)}</span>
          <span className={cn('tabular inline-flex items-center gap-0.5 text-[9px] font-semibold', up ? 'text-up' : 'text-down')}>
            {up ? <TrendingUp className="h-2.5 w-2.5" /> : <TrendingDown className="h-2.5 w-2.5" />}
            {fmtSignedPercent(change)}
          </span>
        </>
      )}
    </div>
  )
}

export function HeaderTicker() {
  const { data: theses = [] } = useTheses()
  // Only surface strong buy stocks (conviction ≥ 4) in the header feed
  const tickers = [...new Set(
    theses
      .filter(t => t.status === 'open' && t.conviction >= 4)
      .flatMap(t => t.tickers ?? [])
  )]

  if (tickers.length === 0) return null

  // Duplicate so the marquee loops seamlessly
  const both = [...tickers, ...tickers]

  return (
    <div className="relative flex flex-1 overflow-hidden border-r border-border">
      {/* Fade edges */}
      <div className="pointer-events-none absolute inset-y-0 left-0 z-10 w-6 bg-gradient-to-r from-bg-panel to-transparent" />
      <div className="pointer-events-none absolute inset-y-0 right-0 z-10 w-6 bg-gradient-to-l from-bg-panel to-transparent" />

      <div
        className="flex items-stretch"
        style={{
          animation: `ticker-scroll ${tickers.length * 4}s linear infinite`,
          willChange: 'transform',
        }}
      >
        {both.map((t, i) => <TickerChip key={`${t}-${i}`} ticker={t} />)}
      </div>

      <style>{`
        @keyframes ticker-scroll {
          0%   { transform: translateX(0); }
          100% { transform: translateX(-50%); }
        }
      `}</style>
    </div>
  )
}
