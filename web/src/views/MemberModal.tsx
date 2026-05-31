import { useEffect, useMemo, useState } from 'react'
import {
  Bar,
  BarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { ExternalLink, X } from 'lucide-react'

import { useCongressMember } from '@/lib/api'
import { TickerLogo } from '@/components/ui/TickerLogo'
import { cn, fmtCompact, fmtDate, stripTitle } from '@/lib/utils'

const fmtUsd = (v: number | null | undefined) =>
  v == null || Number.isNaN(v) ? '—' : `$${fmtCompact(v)}`

const monthLabel = (m: string) => {
  const [y, mo] = m.split('-')
  const names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  return `${names[Number(mo) - 1] ?? mo} '${y.slice(2)}`
}

const PARTY_COLORS: Record<string, string> = {
  Democrat: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  Republican: 'bg-red-500/20 text-red-400 border-red-500/30',
  Independent: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
}

const CHAMBER_COLORS: Record<string, string> = {
  senate: 'bg-cyan/10 text-cyan border-cyan/30',
  house: 'bg-warn/10 text-warn border-warn/30',
}

type TradeSort = 'date' | 'amount' | 'ticker'

const MEMBER_WINDOW_DAYS = 730

export function MemberModal({ name, onClose }: { name: string; onClose: () => void }) {
  const { data, isLoading, isError } = useCongressMember(name, MEMBER_WINDOW_DAYS)
  const [sort, setSort] = useState<TradeSort>('date')

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  const sortedTrades = useMemo(() => {
    const trades = [...(data?.trades ?? [])]
    if (sort === 'ticker') trades.sort((a, b) => a.ticker.localeCompare(b.ticker))
    else if (sort === 'amount') {
      const mid = (s: string) => {
        const nums = (s ?? '').match(/[\d,]+/g)?.map(n => parseFloat(n.replace(/,/g, ''))) ?? []
        return nums.length === 0 ? 0 : nums.length === 1 ? nums[0] : (nums[0] + nums[1]) / 2
      }
      trades.sort((a, b) => mid(b.amount) - mid(a.amount))
    }
    return trades
  }, [data, sort])

  const member = data?.member
  const t = data?.totals
  const buyTilt = t && t.trades > 0 ? Math.round((t.buys / t.trades) * 100) : null

  const timelineData = useMemo(
    () => (data?.timeline ?? []).map(m => ({
      month: monthLabel(m.month),
      buy: m.buy_notional,
      sell: -m.sell_notional,
    })),
    [data],
  )

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/70 pt-8 backdrop-blur-sm"
      onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="relative flex max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden border border-border bg-bg-panel shadow-2xl">

        {/* ── Header ── */}
        <div className="flex shrink-0 items-center gap-4 border-b border-border p-5">
          {/* Photo — always render initials fallback; hide it only if photo loads */}
          <div className="relative h-16 w-16 shrink-0">
            <div className="flex h-16 w-16 items-center justify-center rounded-full border-2 border-border bg-border text-lg font-bold text-faint">
              {stripTitle(member?.name ?? name).split(' ').filter(Boolean).map(p => p[0]).slice(0, 2).join('')}
            </div>
            {member?.photo_url && (
              <img
                src={member.photo_url}
                alt={member.name}
                className="absolute inset-0 h-16 w-16 rounded-full border-2 border-border object-cover object-top"
                onError={e => { (e.target as HTMLImageElement).style.display = 'none' }}
              />
            )}
          </div>

          {/* Name + badges */}
          <div className="min-w-0 flex-1">
            <h2 className="truncate font-sans text-lg font-semibold text-ink">
              {stripTitle(member?.name ?? name)}
            </h2>
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
              {member?.party && (
                <span className={cn('num border px-2 py-0.5 text-[10px] font-semibold', PARTY_COLORS[member.party] ?? 'border-border text-faint')}>
                  {member.party.toUpperCase()}
                </span>
              )}
              {member?.chamber && (
                <span className={cn('num border px-2 py-0.5 text-[10px] font-semibold', CHAMBER_COLORS[member.chamber] ?? 'border-border text-faint')}>
                  {member.chamber.toUpperCase()}
                </span>
              )}
              {member?.state && (
                <span className="num border border-border px-2 py-0.5 text-[10px] text-faint">
                  {member.state}{member.district != null ? `-${member.district}` : ''}
                </span>
              )}
            </div>
          </div>

            <div className="flex shrink-0 flex-col items-end gap-1">
            <button onClick={onClose} className="text-faint hover:text-ink">
              <X className="h-5 w-5" />
            </button>
            <span className="num text-[9px] text-faint">LAST {MEMBER_WINDOW_DAYS / 365}Y</span>
          </div>
        </div>

        {isLoading ? (
          <div className="flex flex-1 items-center justify-center py-16">
            <span className="num text-sm text-muted">LOADING PROFILE…</span>
          </div>
        ) : isError ? (
          <div className="flex flex-1 items-center justify-center py-16">
            <span className="num text-sm text-down">FAILED TO LOAD PROFILE — check connection and try again</span>
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto">

            {/* ── KPI bar ── */}
            <div className="flex shrink-0 flex-wrap border-b border-border">
              {[
                { label: 'TOTAL TRADES', value: t?.trades ?? '—', tone: 'cyan' as const },
                { label: 'BUY TILT', value: buyTilt != null ? `${buyTilt}%` : '—', tone: (buyTilt ?? 0) >= 50 ? 'up' as const : 'down' as const },
                { label: 'EST. BOUGHT', value: fmtUsd(t?.buy_notional), tone: 'up' as const },
                { label: 'EST. SOLD', value: fmtUsd(t?.sell_notional), tone: 'down' as const },
                { label: 'TICKERS', value: t?.tickers ?? '—', tone: 'muted' as const },
                { label: 'MEDIAN LAG', value: t?.median_lag_days != null ? `${t.median_lag_days}d` : '—', tone: 'warn' as const },
              ].map(({ label, value, tone }) => {
                const colors = { up: 'text-up', down: 'text-down', warn: 'text-warn', muted: 'text-muted', cyan: 'text-cyan' }
                return (
                  <div key={label} className="flex flex-col gap-0.5 border-r border-border px-4 py-3 last:border-r-0">
                    <span className="label text-[9px]">{label}</span>
                    <span className={cn('num text-xl font-semibold leading-none', colors[tone])}>{value}</span>
                  </div>
                )
              })}
            </div>

            <div className="grid gap-4 p-4 lg:grid-cols-2">

              {/* ── Buy/sell timeline ── */}
              {timelineData.length > 0 && (
                <section className="border border-border bg-bg p-3 lg:col-span-2">
                  <span className="num mb-2 block text-[11px] font-semibold tracking-widest text-cyan">
                    MONTHLY BUY / SELL FLOW
                  </span>
                  <ResponsiveContainer width="100%" height={120}>
                    <BarChart data={timelineData} barGap={1} barCategoryGap="20%">
                      <XAxis dataKey="month" tick={{ fontSize: 9, fill: '#6b7280' }} tickLine={false} axisLine={false} />
                      <YAxis tick={{ fontSize: 9, fill: '#6b7280' }} tickLine={false} axisLine={false}
                        tickFormatter={v => `$${fmtCompact(Math.abs(v))}`} />
                      <Tooltip
                        formatter={(v) => [`$${fmtCompact(Math.abs(Number(v)))}`, Number(v) > 0 ? 'Bought' : 'Sold']}
                        contentStyle={{ background: '#111', border: '1px solid #333', fontSize: 11 }}
                      />
                      <Bar dataKey="buy" fill="rgba(34,197,94,0.5)" radius={[2, 2, 0, 0]} />
                      <Bar dataKey="sell" fill="rgba(239,68,68,0.5)" radius={[2, 2, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </section>
              )}

              {/* ── Top tickers ── */}
              <section className="border border-border bg-bg p-3">
                <span className="num mb-2 block text-[11px] font-semibold tracking-widest text-cyan">TOP TICKERS</span>
                {data?.top_tickers.length === 0 ? (
                  <p className="num text-[11px] text-faint">No data</p>
                ) : (
                  <div className="flex flex-col gap-1">
                    {data?.top_tickers.map(r => {
                      const net = r.net_notional
                      const gross = r.buy_notional + r.sell_notional
                      return (
                        <div key={r.ticker} className="flex items-center gap-2">
                          <TickerLogo ticker={r.ticker} size={16} className="shrink-0" />
                          <span className="num w-14 shrink-0 text-[11px] font-semibold text-cyan">{r.ticker}</span>
                          <div className="relative h-2 flex-1 bg-border/30">
                            <div className="absolute left-1/2 top-0 h-full w-px bg-border-bright" />
                            {r.sell_notional > 0 && (
                              <div className="absolute top-0 h-full bg-down/60"
                                style={{ right: '50%', width: `${(r.sell_notional / Math.max(gross, 1)) * 50}%` }} />
                            )}
                            {r.buy_notional > 0 && (
                              <div className="absolute top-0 h-full bg-up/60"
                                style={{ left: '50%', width: `${(r.buy_notional / Math.max(gross, 1)) * 50}%` }} />
                            )}
                          </div>
                          <span className={cn('num w-16 shrink-0 text-right text-[10px]', net >= 0 ? 'text-up' : 'text-down')}>
                            {net >= 0 ? '+' : '−'}{fmtUsd(Math.abs(net)).slice(1)}
                          </span>
                          <span className="num w-12 shrink-0 text-right text-[9px] text-faint">
                            {r.buys > 0 && <span className="text-up">{r.buys}B</span>}
                            {r.buys > 0 && r.sells > 0 && ' '}
                            {r.sells > 0 && <span className="text-down">{r.sells}S</span>}
                          </span>
                        </div>
                      )
                    })}
                  </div>
                )}
              </section>

              {/* ── Buy/sell ratio donut ── */}
              <section className="border border-border bg-bg p-3">
                <span className="num mb-3 block text-[11px] font-semibold tracking-widest text-cyan">TRADING FINGERPRINT</span>
                <div className="space-y-2.5">
                  {[
                    { label: 'Buy tilt', value: buyTilt != null ? `${buyTilt}%` : '—', tone: 'text-up' },
                    { label: 'Est. bought', value: fmtUsd(t?.buy_notional), tone: 'text-up' },
                    { label: 'Est. sold', value: fmtUsd(t?.sell_notional), tone: 'text-down' },
                    { label: 'Unique tickers', value: t?.tickers ?? '—', tone: 'text-muted' },
                    { label: 'Median disclosure lag', value: t?.median_lag_days != null ? `${t.median_lag_days} days` : '—', tone: 'text-warn' },
                  ].map(({ label, value, tone }) => (
                    <div key={label} className="flex items-baseline justify-between border-b border-border-dim pb-2">
                      <span className="font-sans text-[11px] text-faint">{label}</span>
                      <span className={cn('num text-[12px] font-semibold', tone)}>{value}</span>
                    </div>
                  ))}
                </div>
              </section>

              {/* ── Trade history ── */}
              <section className="border border-border bg-bg p-3 lg:col-span-2">
                <div className="mb-2 flex items-center gap-3">
                  <span className="num text-[11px] font-semibold tracking-widest text-cyan">ALL TRADES</span>
                  <span className="label text-[9px]">SORT</span>
                  {(['date', 'amount', 'ticker'] as TradeSort[]).map(s => (
                    <button key={s} onClick={() => setSort(s)}
                      className={cn('num border px-1.5 py-0.5 text-[9px] font-semibold transition-colors',
                        sort === s ? 'border-cyan text-cyan' : 'border-border text-faint hover:border-border-bright hover:text-muted')}>
                      {s.toUpperCase()}
                    </button>
                  ))}
                  <span className="num ml-auto text-[10px] text-faint">{sortedTrades.length} records</span>
                </div>
                <div className="max-h-72 overflow-y-auto">
                  <table className="w-full border-collapse">
                    <thead className="sticky top-0 bg-bg">
                      <tr className="border-b border-border text-left">
                        <th className="label px-2 py-1">TICKER</th>
                        <th className="label px-2 py-1">ACTION</th>
                        <th className="label px-2 py-1 text-right">AMOUNT</th>
                        <th className="label px-2 py-1 text-right">TRADED</th>
                        <th className="label px-2 py-1 text-right">DISCLOSED</th>
                        <th className="label px-2 py-1 text-right">LAG</th>
                        <th className="label px-2 py-1" />
                      </tr>
                    </thead>
                    <tbody>
                      {sortedTrades.map((tr, i) => {
                        const buy = tr.transaction_type.toLowerCase().includes('purchase') ||
                          tr.transaction_type.trim().toLowerCase() === 'p'
                        return (
                          <tr key={i} className="border-b border-border-dim hover:bg-bg-hover">
                            <td className="px-2 py-1.5">
                              <div className="flex items-center gap-1.5">
                                <TickerLogo ticker={tr.ticker} size={14} />
                                <span className="num text-[11px] font-semibold text-cyan">{tr.ticker}</span>
                              </div>
                            </td>
                            <td className={cn('num px-2 py-1.5 text-[11px]', buy ? 'text-up' : 'text-down')}>
                              {buy ? 'BUY' : 'SELL'}
                              {tr.transaction_type.toLowerCase().includes('partial') && (
                                <span className="ml-1 text-[9px] text-faint">(partial)</span>
                              )}
                            </td>
                            <td className="num px-2 py-1.5 text-right text-[11px] text-faint">{tr.amount}</td>
                            <td className="num px-2 py-1.5 text-right text-[10px] text-faint">{fmtDate(tr.transaction_date)}</td>
                            <td className="num px-2 py-1.5 text-right text-[10px] text-muted">{fmtDate(tr.disclosure_date)}</td>
                            <td className={cn('num px-2 py-1.5 text-right text-[10px]',
                              tr.lag_days == null ? 'text-faint'
                              : tr.lag_days > 45 ? 'text-down'
                              : tr.lag_days > 30 ? 'text-warn'
                              : 'text-up')}>
                              {tr.lag_days != null ? `${tr.lag_days}d` : '—'}
                            </td>
                            <td className="px-2 py-1.5 text-right">
                              {tr.report_url && (
                                <a href={tr.report_url} target="_blank" rel="noreferrer"
                                  className="inline-flex text-faint hover:text-cyan">
                                  <ExternalLink className="h-3 w-3" />
                                </a>
                              )}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </section>

            </div>
          </div>
        )}
      </div>
    </div>
  )
}
