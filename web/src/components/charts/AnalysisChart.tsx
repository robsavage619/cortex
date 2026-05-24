import {
  AreaSeries,
  ColorType,
  createChart,
  LineStyle,
  LineSeries,
  type IChartApi,
  type Time,
} from 'lightweight-charts'
import { useEffect, useRef } from 'react'

import type { PriceBar } from '@/lib/types'

function sma(closes: number[], period: number): (number | null)[] {
  return closes.map((_, i) => {
    if (i < period - 1) return null
    return closes.slice(i - period + 1, i + 1).reduce((a, b) => a + b, 0) / period
  })
}

export function AnalysisChart({
  bars,
  entryPrice,
  height = 240,
  showSMA = true,
}: {
  bars: PriceBar[]
  entryPrice?: number | null
  height?: number
  showSMA?: boolean
}) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!ref.current || bars.length === 0) return

    const up = bars[bars.length - 1].close >= bars[0].close
    const accent = up ? '#34d399' : '#f87171'

    const chart: IChartApi = createChart(ref.current, {
      height,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#6b7280',
        fontFamily: '"Geist Mono Variable", monospace',
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: 'rgba(255,255,255,0.03)' },
        horzLines: { color: 'rgba(255,255,255,0.05)' },
      },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.06)' },
      timeScale: { borderColor: 'rgba(255,255,255,0.06)', fixLeftEdge: true },
      crosshair: {
        vertLine: { color: 'rgba(34,211,238,0.4)', labelBackgroundColor: '#0d1117' },
        horzLine: { color: 'rgba(34,211,238,0.4)', labelBackgroundColor: '#0d1117' },
      },
    })

    const area = chart.addSeries(AreaSeries, {
      lineColor: accent,
      topColor: up ? 'rgba(52,211,153,0.18)' : 'rgba(248,113,113,0.18)',
      bottomColor: 'rgba(10,14,26,0)',
      lineWidth: 2,
      priceLineVisible: false,
    })
    area.setData(bars.map(b => ({ time: b.date as Time, value: b.close })))

    if (showSMA && bars.length >= 20) {
      const closes = bars.map(b => b.close)
      const sma20 = sma(closes, 20)
      const sma50 = bars.length >= 50 ? sma(closes, 50) : []

      const sma20Data = bars
        .map((b, i) => sma20[i] != null ? { time: b.date as Time, value: sma20[i]! } : null)
        .filter((x): x is { time: Time; value: number } => x !== null)

      if (sma20Data.length > 0) {
        const l20 = chart.addSeries(LineSeries, {
          color: 'rgba(251,191,36,0.8)',
          lineWidth: 1,
          lineStyle: LineStyle.Solid,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
          title: '20d avg',
        })
        l20.setData(sma20Data)
      }

      if (sma50.length > 0) {
        const sma50Data = bars
          .map((b, i) => sma50[i] != null ? { time: b.date as Time, value: sma50[i]! } : null)
          .filter((x): x is { time: Time; value: number } => x !== null)
        if (sma50Data.length > 0) {
          const l50 = chart.addSeries(LineSeries, {
            color: 'rgba(129,140,248,0.8)',
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            priceLineVisible: false,
            lastValueVisible: false,
            crosshairMarkerVisible: false,
            title: '50d avg',
          })
          l50.setData(sma50Data)
        }
      }
    }

    if (entryPrice) {
      area.createPriceLine({
        price: entryPrice,
        color: 'rgba(139,92,246,0.7)',
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: 'entry',
      })
    }

    chart.timeScale().fitContent()

    const ro = new ResizeObserver(() => {
      if (ref.current) chart.applyOptions({ width: ref.current.clientWidth })
    })
    ro.observe(ref.current)

    return () => {
      ro.disconnect()
      chart.remove()
    }
  }, [bars, entryPrice, height, showSMA])

  return <div ref={ref} className="w-full" style={{ height }} />
}
