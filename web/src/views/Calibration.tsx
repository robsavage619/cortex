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

import { Card, CardTitle } from '@/components/ui/Card'
import { Pill } from '@/components/ui/Badge'
import { EmptyState, ErrorState, Loading } from '@/components/ui/States'
import { StatTile } from '@/components/ui/StatTile'
import { useCalibration } from '@/lib/api'
import { fmtPercent } from '@/lib/utils'

export function Calibration() {
  const cal = useCalibration()

  if (cal.isLoading) return <Loading label="Computing calibration…" />
  if (cal.isError) return <ErrorState error={cal.error} />
  const data = cal.data

  if (!data || data.buckets.length === 0) {
    return (
      <div className="space-y-6">
        <Header />
        <EmptyState title="No reviewed theses yet">
          Calibration unlocks once you've reviewed theses. Each graded outcome sharpens
          the picture of how well your conviction matches reality.
        </EmptyState>
      </div>
    )
  }

  const curve = data.buckets.map((b) => ({
    expected: b.conviction / 5,
    actual: b.hit_rate,
    label: `${b.conviction}/5`,
    n: b.total,
  }))

  return (
    <div className="space-y-6">
      <Header />

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-3">
        <StatTile label="Brier score" value={data.brier_score.toFixed(3)} hint="0 = perfect" />
        <StatTile
          label="Confidence bias"
          value={data.overconfident ? 'Over' : 'Calibrated'}
          delta={
            data.overconfident
              ? { value: 'overconfident', tone: 'down' }
              : { value: 'on track', tone: 'up' }
          }
        />
        <StatTile label="Buckets" value={data.buckets.length} />
      </div>

      <Card>
        <CardTitle className="mb-4">Reliability diagram</CardTitle>
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={curve} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
              <CartesianGrid stroke="rgba(255,255,255,0.08)" />
              <XAxis
                dataKey="expected"
                type="number"
                domain={[0, 1]}
                tickFormatter={(v) => fmtPercent(v, 0)}
                stroke="#8b93a7"
                fontSize={12}
              />
              <YAxis
                domain={[0, 1]}
                tickFormatter={(v) => fmtPercent(v, 0)}
                stroke="#8b93a7"
                fontSize={12}
              />
              <Tooltip
                contentStyle={{
                  background: '#0a0e1a',
                  border: '1px solid rgba(255,255,255,0.08)',
                  borderRadius: 12,
                }}
                formatter={(v) => fmtPercent(Number(v))}
                labelFormatter={(v) => `Conviction ${fmtPercent(Number(v), 0)}`}
              />
              <ReferenceLine
                segment={[
                  { x: 0, y: 0 },
                  { x: 1, y: 1 },
                ]}
                stroke="#5a6177"
                strokeDasharray="4 4"
              />
              <Line
                type="monotone"
                dataKey="actual"
                stroke="#8b5cf6"
                strokeWidth={2.5}
                dot={{ fill: '#22d3ee', r: 4 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <p className="mt-2 text-xs text-faint">
          Dashed line is perfect calibration. Points below it mean you were overconfident.
        </p>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardTitle className="mb-4">Hit rate by conviction</CardTitle>
          <div className="space-y-3">
            {data.buckets.map((b) => (
              <div key={b.conviction} className="flex items-center gap-3">
                <span className="tabular w-8 text-sm text-muted">{b.conviction}/5</span>
                <div className="h-2 flex-1 overflow-hidden rounded-full bg-hairline">
                  <div
                    className="accent-gradient h-full rounded-full"
                    style={{ width: `${b.hit_rate * 100}%` }}
                  />
                </div>
                <span className="tabular w-24 text-right text-sm text-ink">
                  {fmtPercent(b.hit_rate)} ({b.correct}/{b.total})
                </span>
              </div>
            ))}
          </div>
        </Card>

        <Card>
          <CardTitle className="mb-4">Per author</CardTitle>
          <div className="space-y-2">
            {Object.entries(data.per_author).map(([author, score]) => (
              <div key={author} className="flex items-center justify-between">
                <span className="capitalize text-ink">{author}</span>
                <Pill tone={score <= 0.25 ? 'up' : score >= 0.4 ? 'down' : 'muted'}>
                  Brier {score.toFixed(3)}
                </Pill>
              </div>
            ))}
            {Object.keys(data.per_author).length === 0 && (
              <p className="text-sm text-faint">No per-author data yet.</p>
            )}
          </div>
        </Card>
      </div>
    </div>
  )
}

function Header() {
  return (
    <header>
      <h1 className="text-2xl font-semibold tracking-tight">Calibration</h1>
      <p className="text-sm text-muted">
        How well your conviction matches outcomes. The whole point of the system is to move
        this toward the diagonal over time.
      </p>
    </header>
  )
}
