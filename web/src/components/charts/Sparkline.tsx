import { useId } from 'react'

export function Sparkline({
  values,
  width = 96,
  height = 28,
  tone,
}: {
  values: number[]
  width?: number
  height?: number
  tone?: 'up' | 'down'
}) {
  const id = useId()
  if (values.length < 2) {
    return <div style={{ width, height }} className="rounded bg-hairline/40" />
  }

  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const step = width / (values.length - 1)
  const y = (v: number) => height - ((v - min) / span) * (height - 2) - 1

  const dir = tone ?? (values[values.length - 1] >= values[0] ? 'up' : 'down')
  const stroke = dir === 'up' ? '#34d399' : '#f87171'

  const line = values.map((v, i) => `${i * step},${y(v)}`).join(' ')
  const area = `0,${height} ${line} ${width},${height}`

  return (
    <svg width={width} height={height} className="overflow-visible">
      <defs>
        <linearGradient id={`spark-${id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity="0.28" />
          <stop offset="100%" stopColor={stroke} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={area} fill={`url(#spark-${id})`} />
      <polyline
        points={line}
        fill="none"
        stroke={stroke}
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  )
}
