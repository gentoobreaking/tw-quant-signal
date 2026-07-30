import { useEffect, useRef } from 'react'
import { createChart, ColorType, CandlestickSeries, LineSeries } from 'lightweight-charts'
import type { PricePoint, IndicatorPoint } from '../types'

interface Props {
  prices: PricePoint[]
  indicators: IndicatorPoint[]
}

export default function PriceChart({ prices, indicators }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!containerRef.current || prices.length === 0) return

    const chart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: '#1a1d28' }, textColor: '#888ca6' },
      grid: { vertLines: { color: '#2a2d3a' }, horzLines: { color: '#2a2d3a' } },
      crosshair: { mode: 0 },
      width: containerRef.current.clientWidth,
      height: 400,
    })

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#26a69a', downColor: '#ef5350', borderDownColor: '#ef5350', borderUpColor: '#26a69a',
      wickDownColor: '#ef5350', wickUpColor: '#26a69a',
    })

    const data = prices
      .slice()
      .reverse()
      .map(p => ({
        time: p.date,
        open: p.close || 0,
        high: p.high || p.close || 0,
        low: p.low || p.close || 0,
        close: p.close || 0,
      }))

    candleSeries.setData(data as any)

    const indReversed = indicators.slice().reverse()
    if (indReversed.length > 0) {
      const lineMA5 = chart.addSeries(LineSeries, { color: '#42a5f5', lineWidth: 1, lineStyle: 2 })
      const lineMA20 = chart.addSeries(LineSeries, { color: '#ffa726', lineWidth: 1 })
      const lineMA60 = chart.addSeries(LineSeries, { color: '#ef5350', lineWidth: 1 })
      lineMA5.setData(indReversed.filter(p => p.ma5 != null).map(p => ({ time: p.date, value: p.ma5! })))
      lineMA20.setData(indReversed.filter(p => p.ma20 != null).map(p => ({ time: p.date, value: p.ma20! })))
      lineMA60.setData(indReversed.filter(p => p.ma60 != null).map(p => ({ time: p.date, value: p.ma60! })))
    }

    chart.timeScale().fitContent()

    const handleResize = () => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth })
    }
    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
      chart.remove()
    }
  }, [prices, indicators])

  return <div ref={containerRef} className="chart-container" />
}
