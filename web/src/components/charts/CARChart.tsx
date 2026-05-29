import type { DailyCARPoint } from '@/lib/types'

const HORIZONS = [5, 20, 60, 120]

export function CARChart({ series }: { series: DailyCARPoint[] }) {
  if (series.length === 0) return null

  const maxDay = series[series.length - 1].day
  const W = maxDay + 1
  const H = 200  // internal SVG height units (more precision)

  const allUpper = series.map(d => d.mean_car + d.se)
  const allLower = series.map(d => d.mean_car - d.se)
  const yMin = Math.min(Math.min(...allLower), -0.015)
  const yMax = Math.max(Math.max(...allUpper), 0.015)
  const yRange = yMax - yMin

  const sy = (v: number) => H - ((v - yMin) / yRange) * H
  const zeroY = sy(0)

  const meanPath = series
    .map((d, i) => `${i === 0 ? 'M' : 'L'}${d.day},${sy(d.mean_car).toFixed(1)}`)
    .join(' ')

  const upperPts = series.map(d => `${d.day},${sy(d.mean_car + d.se).toFixed(1)}`)
  const lowerPts = [...series].reverse().map(d => `${d.day},${sy(d.mean_car - d.se).toFixed(1)}`)
  const bandPath = `M${upperPts.join(' L')} L${lowerPts.join(' L')} Z`

  const n = series[0]?.n ?? 0
  const last = series[series.length - 1]
  const isPositive = (last?.mean_car ?? 0) >= 0

  return (
    <div className="space-y-1.5">
      <div className="relative h-16 border border-border bg-bg">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="h-full w-full"
          preserveAspectRatio="none"
        >
          {/* Confidence band (±1 SE) */}
          <path d={bandPath} fill="rgba(52,211,153,0.10)" />
          {/* Zero baseline */}
          <line
            x1={0} y1={zeroY}
            x2={W} y2={zeroY}
            stroke="rgba(255,255,255,0.12)"
            strokeWidth="1"
          />
          {/* Horizon tick lines */}
          {HORIZONS.filter(h => h < maxDay).map(h => (
            <line
              key={h}
              x1={h} y1={0}
              x2={h} y2={H}
              stroke="rgba(255,255,255,0.06)"
              strokeWidth="0.8"
              strokeDasharray="3,4"
            />
          ))}
          {/* Mean CAR line */}
          <path
            d={meanPath}
            fill="none"
            stroke={isPositive ? '#34d399' : '#f87171'}
            strokeWidth="1.5"
          />
        </svg>

        {/* Axis labels — overlaid on the chart corners */}
        <span className="pointer-events-none absolute right-1 top-0.5 num text-[7px] text-muted/50">
          {(yMax * 100).toFixed(1)}%
        </span>
        <span className="pointer-events-none absolute bottom-0.5 right-1 num text-[7px] text-muted/50">
          {(yMin * 100).toFixed(1)}%
        </span>

        {/* Horizon day labels along the bottom */}
        {HORIZONS.filter(h => h <= maxDay).map(h => (
          <span
            key={h}
            className="pointer-events-none absolute bottom-0.5 num text-[7px] text-muted/40"
            style={{ left: `${(h / maxDay) * 100}%` }}
          >
            +{h}d
          </span>
        ))}
      </div>

      {/* Key horizon stats */}
      <div className="flex items-center gap-3">
        {HORIZONS.map(h => {
          const pt = series[h]
          if (!pt) return null
          const pct = (pt.mean_car * 100).toFixed(2)
          const pos = pt.mean_car >= 0
          return (
            <span key={h} className="num text-[9px] text-muted">
              +{h}d:{' '}
              <span className={pos ? 'text-up' : 'text-down'}>
                {pos ? '+' : ''}{pct}%
              </span>
            </span>
          )
        })}
        <span className="num text-[9px] text-faint ml-auto">n={n}</span>
      </div>
    </div>
  )
}
