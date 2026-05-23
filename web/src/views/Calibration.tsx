import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { useCalibration } from '@/lib/api'
import { cn, fmtDate, fmtPercent } from '@/lib/utils'

// ── KPI tile ──────────────────────────────────────────────────────────────────

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

// ── Section wrapper ───────────────────────────────────────────────────────────

function Panel({ title, children, className }: {
  title: string; children: React.ReactNode; className?: string
}) {
  return (
    <div className={cn('border border-border bg-bg-panel', className)}>
      <div className="border-b border-border px-5 py-2">
        <span className="label">{title}</span>
      </div>
      {children}
    </div>
  )
}

// ── Main ──────────────────────────────────────────────────────────────────────

export function Calibration() {
  const cal = useCalibration()

  if (cal.isLoading) {
    return <div className="flex flex-1 items-center justify-center">
      <span className="num text-sm text-muted">COMPUTING CALIBRATION…</span>
    </div>
  }

  const data = cal.data

  const hits    = data?.buckets.reduce((s, b) => s + b.correct, 0) ?? 0
  const total   = data?.buckets.reduce((s, b) => s + b.total, 0) ?? 0
  const hitRate = total > 0 ? `${((hits / total) * 100).toFixed(0)}%` : '—'

  const curve = (data?.buckets ?? []).map(b => ({
    expected: b.conviction / 5,
    actual:   b.hit_rate,
    label:    `${b.conviction}/5`,
    n:        b.total,
  }))

  const trend = (data?.trend ?? []).map(p => ({
    date:  fmtDate(p.reviewed_on),
    brier: Number(p.brier.toFixed(3)),
  }))

  const processScore = data?.process_score

  return (
    <div className="flex flex-1 flex-col overflow-hidden">

      {/* ── KPI bar ─────────────────────────────────────── */}
      <div className="flex shrink-0 items-stretch border-b border-border bg-bg-panel">
        <Kpi label="BRIER SCORE"
          value={data ? data.brier_score.toFixed(3) : '—'}
          sub="0 = PERFECT · 0.25 = RANDOM"
          tone={data ? (data.overconfident ? 'warn' : 'up') : 'muted'} />
        <Kpi label="HIT RATE"    value={hitRate}   sub={`${total} REVIEWED`} tone={hits > 0 ? 'up' : 'muted'} />
        <Kpi label="PROCESS SCORE"
          value={processScore != null ? `${(processScore * 100).toFixed(0)}%` : '—'}
          sub="GOOD / (GOOD + FLAWED)"
          tone={processScore != null ? (processScore >= 0.6 ? 'up' : 'warn') : 'muted'} />
        <Kpi label="CALIBRATION"
          value={data ? (data.overconfident ? 'OVER' : 'ON TRACK') : '—'}
          tone={data?.overconfident ? 'warn' : 'muted'} />
      </div>

      {total === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 py-24">
          <span className="num text-sm text-muted">NO REVIEWED THESES</span>
          <p className="font-sans text-[12px] text-faint max-w-sm text-center">
            Calibration unlocks once you've reviewed theses. Each graded outcome sharpens
            how well your conviction buckets map to actual outcomes.
          </p>
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto p-5 space-y-5">

          <div className="grid gap-5 lg:grid-cols-2">

            {/* Reliability diagram */}
            <Panel title="RELIABILITY DIAGRAM — CONVICTION vs ACTUAL HIT RATE">
              <div className="p-5">
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={curve} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
                      <CartesianGrid stroke="rgba(255,255,255,0.05)" strokeDasharray="2 2" />
                      <XAxis
                        dataKey="expected" type="number" domain={[0, 1]}
                        tickFormatter={v => fmtPercent(v, 0)}
                        stroke="#4b5563" fontSize={10} fontFamily="var(--font-mono)"
                        tickLine={false}
                      />
                      <YAxis
                        domain={[0, 1]}
                        tickFormatter={v => fmtPercent(v, 0)}
                        stroke="#4b5563" fontSize={10} fontFamily="var(--font-mono)"
                        tickLine={false} axisLine={false}
                      />
                      <Tooltip
                        contentStyle={{
                          background: 'var(--color-bg-panel)',
                          border: '1px solid var(--color-border)',
                          borderRadius: '2px',
                          fontFamily: 'var(--font-mono)',
                          fontSize: '11px',
                        }}
                        formatter={v => [fmtPercent(Number(v)), 'actual hit rate']}
                        labelFormatter={v => `conviction ${fmtPercent(Number(v), 0)}`}
                      />
                      {/* Perfect calibration diagonal */}
                      <ReferenceLine
                        segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]}
                        stroke="#374151" strokeDasharray="4 4"
                      />
                      <Line
                        type="monotone" dataKey="actual"
                        stroke="#22d3ee" strokeWidth={2}
                        dot={{ fill: '#22d3ee', r: 4, strokeWidth: 0 }}
                        activeDot={{ r: 5, fill: '#ffffff' }}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
                <p className="num mt-2 text-[10px] text-faint">
                  DASHED = PERFECT CALIBRATION · POINTS BELOW = OVERCONFIDENT
                </p>
              </div>
            </Panel>

            {/* Hit rate by conviction */}
            <Panel title="HIT RATE BY CONVICTION BUCKET">
              <div className="p-5 space-y-3">
                {data?.buckets.map(b => {
                  const pct = b.hit_rate * 100
                  const color = pct >= 60 ? 'bg-up' : pct >= 40 ? 'bg-warn' : 'bg-down'
                  return (
                    <div key={b.conviction} className="flex items-center gap-3">
                      <span className="num w-8 shrink-0 text-[11px] text-muted">{b.conviction}/5</span>
                      <div className="h-1.5 flex-1 bg-border">
                        <div className={cn('h-full transition-all', color)}
                          style={{ width: `${pct}%` }} />
                      </div>
                      <span className="num w-28 shrink-0 text-right text-[11px] text-ink">
                        {fmtPercent(b.hit_rate)} <span className="text-faint">({b.correct}/{b.total})</span>
                      </span>
                    </div>
                  )
                })}
              </div>
            </Panel>

          </div>

          <div className="grid gap-5 lg:grid-cols-2">

            {/* Brier trend */}
            {trend.length > 1 && (
              <Panel title="BRIER SCORE OVER TIME — LOWER IS BETTER">
                <div className="p-5">
                  <div className="h-48">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={trend} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
                        <CartesianGrid stroke="rgba(255,255,255,0.05)" strokeDasharray="2 2" />
                        <XAxis dataKey="date" stroke="#4b5563" fontSize={10}
                          fontFamily="var(--font-mono)" tickLine={false} />
                        <YAxis stroke="#4b5563" fontSize={10} fontFamily="var(--font-mono)"
                          tickLine={false} axisLine={false} domain={['auto', 'auto']} />
                        <Tooltip
                          contentStyle={{
                            background: 'var(--color-bg-panel)',
                            border: '1px solid var(--color-border)',
                            borderRadius: '2px',
                            fontFamily: 'var(--font-mono)',
                            fontSize: '11px',
                          }}
                        />
                        <Line type="monotone" dataKey="brier"
                          stroke="#4ade80" strokeWidth={2}
                          dot={{ fill: '#4ade80', r: 3, strokeWidth: 0 }}
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              </Panel>
            )}

            {/* Per-author breakdown */}
            <Panel title="PER-AUTHOR BRIER SCORE">
              {data && Object.keys(data.per_author).length > 0 ? (
                Object.entries(data.per_author).map(([author, score]) => (
                  <div key={author} className="flex items-center justify-between border-b border-border-dim px-5 py-3 last:border-b-0">
                    <span className="num text-[13px] font-semibold text-ink">{author.toUpperCase()}</span>
                    <div className="text-right">
                      <span className={cn('num text-[18px] font-semibold',
                        score <= 0.2 ? 'text-up' : score >= 0.35 ? 'text-down' : 'text-warn')}>
                        {score.toFixed(3)}
                      </span>
                      <span className="num block text-[10px] text-faint">
                        {score <= 0.2 ? 'WELL CALIBRATED' : score >= 0.35 ? 'OVERCONFIDENT' : 'DEVELOPING'}
                      </span>
                    </div>
                  </div>
                ))
              ) : (
                <div className="px-5 py-4">
                  <p className="font-sans text-[12px] text-faint">No per-author data yet.</p>
                </div>
              )}

              {/* Decision quality breakdown */}
              {data?.decision_counts && (
                <div className="border-t border-border px-5 py-4 space-y-2">
                  <span className="label block mb-2">DECISION QUALITY BREAKDOWN</span>
                  {(['good', 'flawed', 'unknown'] as const).map(k => {
                    const count = data.decision_counts![k] ?? 0
                    const color = k === 'good' ? 'text-up' : k === 'flawed' ? 'text-down' : 'text-faint'
                    return (
                      <div key={k} className="flex items-center justify-between">
                        <span className={cn('num text-[11px] font-semibold tracking-widest', color)}>
                          {k.toUpperCase()}
                        </span>
                        <span className="num text-[13px] text-ink">{count}</span>
                      </div>
                    )
                  })}
                  <p className="font-sans text-[10px] text-faint pt-1">
                    Process score separates decision quality from outcome — anti-resulting.
                  </p>
                </div>
              )}
            </Panel>

          </div>
        </div>
      )}
    </div>
  )
}
