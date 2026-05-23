import {
  AreaSeries,
  ColorType,
  createChart,
  LineStyle,
  type IChartApi,
  type Time,
} from 'lightweight-charts'
import { useEffect, useRef } from 'react'

import type { PriceBar } from '@/lib/types'

export function PriceChart({
  bars,
  entryPrice,
  height = 320,
}: {
  bars: PriceBar[]
  entryPrice?: number | null
  height?: number
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
        textColor: '#8b93a7',
        fontFamily: 'Inter, sans-serif',
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: 'rgba(255,255,255,0.04)' },
        horzLines: { color: 'rgba(255,255,255,0.06)' },
      },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.08)' },
      timeScale: { borderColor: 'rgba(255,255,255,0.08)', fixLeftEdge: true },
      crosshair: {
        vertLine: { color: 'rgba(99,102,241,0.5)', labelBackgroundColor: '#6366f1' },
        horzLine: { color: 'rgba(99,102,241,0.5)', labelBackgroundColor: '#6366f1' },
      },
    })

    const series = chart.addSeries(AreaSeries, {
      lineColor: accent,
      topColor: up ? 'rgba(52,211,153,0.28)' : 'rgba(248,113,113,0.28)',
      bottomColor: 'rgba(10,14,26,0)',
      lineWidth: 2,
      priceLineVisible: false,
    })
    series.setData(bars.map((b) => ({ time: b.date as Time, value: b.close })))

    if (entryPrice) {
      series.createPriceLine({
        price: entryPrice,
        color: '#8b5cf6',
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
  }, [bars, entryPrice, height])

  return <div ref={ref} className="w-full" style={{ height }} />
}
