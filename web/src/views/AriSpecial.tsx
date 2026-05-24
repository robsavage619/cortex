import { useState } from 'react'

import { useVolatilityScreen } from '@/lib/api'
import { cn, fmtDate, fmtPercent, fmtPrice } from '@/lib/utils'
import { StockModal } from '@/views/StockModal'

function Kpi({ label, value, sub, tone }: {
  label: string; value: string | number; sub?: string
  tone?: 'up' | 'down' | 'warn' | 'muted' | 'cyan'
}) {
  const colors = { up: 'text-up', down: 'text-down', warn: 'text-warn', muted: 'text-muted', cyan: 'text-cyan' }
  return (
    <div className="flex flex-col gap-0.5 border-r border-border px-5 py-3 last:border-r-0">
      <span className="label">{label}</span>
      <span className={cn('num text-2xl font-semibold leading-none', colors[tone ?? 'muted'])}>{value}</span>
      {sub && <span className="num mt-0.5 text-[10px] text-faint">{sub}</span>}
    </div>
  )
}

export function AriSpecial() {
  const { data, isLoading, error } = useVolatilityScreen()
  const [ticker, setTicker] = useState<string | null>(null)

  if (isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <span className="num text-sm text-muted">SCANNING UNIVERSE…</span>
      </div>
    )
  }

  const stocks = data?.stocks ?? []
  const lookback = data?.lookback_days ?? 15
  const topScore = stocks[0]?.ari_special_score
  const widestAdr = stocks.reduce<number>(
    (m, s) => Math.max(m, s.avg_dollar_range ?? 0),
    0,
  )

  return (
    <div className="flex flex-1 flex-col overflow-hidden">

      {/* ── KPI bar ─────────────────────────────────────── */}
      <div className="flex shrink-0 items-stretch border-b border-border bg-bg-panel">
        <Kpi label="MATCHES" value={stocks.length} sub={`${lookback}-DAY WINDOW`}
          tone={stocks.length > 0 ? 'cyan' : 'muted'} />
        <Kpi label="TOP SCORE"
          value={topScore != null ? topScore.toFixed(2) : '—'}
          sub="ADR × CONSISTENCY" tone={topScore != null ? 'up' : 'muted'} />
        <Kpi label="WIDEST SWING"
          value={widestAdr > 0 ? fmtPrice(widestAdr) : '—'}
          sub="AVG DAILY HIGH→LOW" tone={widestAdr > 0 ? 'warn' : 'muted'} />
        <Kpi label="LAST RUN"
          value={data?.last_run ? fmtDate(data.last_run) : '—'}
          sub="REFRESH TO UPDATE" tone="muted" />
      </div>

      {/* ── Explainer ───────────────────────────────────── */}
      <div className="shrink-0 border-b border-border bg-bg px-5 py-3">
        <p className="font-sans text-[12px] text-faint max-w-3xl">
          <span className="num font-semibold text-cyan">THE ARI SPECIAL</span> ranks
          stocks by how large <span className="text-ink">and</span> how
          consistently they swing between their daily high and low, measured in
          dollars. Score = Average Daily Range (ADR, $) × a consistency factor
          (steadier swing size scores higher). Top names move a big, repeatable
          dollar amount every day over at least a two-week window.
        </p>
      </div>

      {error ? (
        <div className="flex flex-1 items-center justify-center">
          <span className="num text-sm text-down">SCREEN FAILED — {String(error)}</span>
        </div>
      ) : stocks.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 py-24">
          <span className="num text-sm text-muted">NO SCREEN DATA YET</span>
          <p className="font-sans text-[12px] text-faint max-w-sm text-center">
            Run <span className="num text-cyan">wst vol-screen</span> or hit refresh
            on the dashboard to populate the Ari Special.
          </p>
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto">
          <table className="w-full border-collapse">
            <thead className="sticky top-0 z-10 bg-bg-panel">
              <tr className="border-b border-border text-left">
                <th className="label px-5 py-2 w-12">#</th>
                <th className="label px-3 py-2">TICKER</th>
                <th className="label px-3 py-2 text-right">SCORE</th>
                <th className="label px-3 py-2 text-right">AVG DAILY RANGE</th>
                <th className="label px-3 py-2 text-right">RANGE %</th>
                <th className="label px-3 py-2">CONSISTENCY</th>
                <th className="label px-3 py-2 text-right">AVG CLOSE</th>
              </tr>
            </thead>
            <tbody>
              {stocks.map(s => {
                const cons = s.range_consistency ?? 0
                return (
                  <tr
                    key={s.ticker}
                    onClick={() => setTicker(s.ticker)}
                    className="cursor-pointer border-b border-border-dim transition-colors hover:bg-bg-hover"
                  >
                    <td className="num px-5 py-2.5 text-[12px] text-faint">{s.rank}</td>
                    <td className="num px-3 py-2.5 text-[13px] font-semibold text-cyan">{s.ticker}</td>
                    <td className="num px-3 py-2.5 text-right text-[13px] text-ink">
                      {s.ari_special_score.toFixed(2)}
                    </td>
                    <td className="num px-3 py-2.5 text-right text-[13px] text-warn">
                      {fmtPrice(s.avg_dollar_range)}
                    </td>
                    <td className="num px-3 py-2.5 text-right text-[12px] text-muted">
                      {fmtPercent(s.avg_range_pct)}
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-2">
                        <div className="h-1.5 w-24 bg-border">
                          <div
                            className={cn('h-full transition-all',
                              cons >= 0.6 ? 'bg-up' : cons >= 0.45 ? 'bg-warn' : 'bg-down')}
                            style={{ width: `${Math.min(100, cons * 100)}%` }}
                          />
                        </div>
                        <span className="num text-[11px] text-faint">{cons.toFixed(2)}</span>
                      </div>
                    </td>
                    <td className="num px-3 py-2.5 text-right text-[12px] text-muted">
                      {fmtPrice(s.avg_close)}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {ticker && <StockModal ticker={ticker} onClose={() => setTicker(null)} />}
    </div>
  )
}
