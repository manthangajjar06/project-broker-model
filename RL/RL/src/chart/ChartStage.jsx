import { useLayoutEffect, useRef, useState } from 'react'
import modelText from '../model/model.txt?raw'
import { findZones, modelFromText } from '../model/zones.js'
import { createPriceChart } from './createPriceChart'
import { FootprintPrimitive } from './footprintPrimitive'
import { LEFT_PAD, candleData, linePoints, showLatest } from './seriesData'
import { ZonePrimitive } from './zonePrimitive'
import { theme } from './theme'

export default function ChartStage({ bars, symbol, onIndexChange }) {
  const containerRef = useRef(null)
  const apiRef = useRef(null)
  const barsRef = useRef(bars)
  const onIndexRef = useRef(onIndexChange)
  const indexByTimeRef = useRef(new Map())
  const [showJump, setShowJump] = useState(false)

  useLayoutEffect(() => {
    barsRef.current = bars
    onIndexRef.current = onIndexChange
    const map = new Map()
    bars.forEach((bar, index) => map.set(bar.time, index))
    indexByTimeRef.current = map
  }, [bars, onIndexChange])

  useLayoutEffect(() => {
    const container = containerRef.current
    if (!container) return undefined

    const api = createPriceChart(container)
    const zones = new ZonePrimitive()
    const footprint = new FootprintPrimitive()
    api.candles.attachPrimitive(zones)
    api.candles.attachPrimitive(footprint)
    api.zones = zones
    api.footprint = footprint

    api.chart.subscribeCrosshairMove((param) => {
      const list = barsRef.current
      if (!list.length) return
      if (param.time == null) {
        onIndexRef.current(list.length - 1)
        return
      }
      const index = indexByTimeRef.current.get(param.time)
      if (index != null) onIndexRef.current(index)
    })

    api.chart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      const count = barsRef.current.length
      if (!range || !count) return
      setShowJump(range.to < LEFT_PAD + count - 2)
    })

    apiRef.current = api
    return () => {
      api.chart.remove()
      apiRef.current = null
    }
  }, [])

  useLayoutEffect(() => {
    const api = apiRef.current
    if (!api || !bars.length) return
    api.candles.setData(candleData(bars))
    api.ema20.setData(linePoints(bars, 'ema20'))
    api.ema50.setData(linePoints(bars, 'ema50'))
    api.watermark.applyOptions({
      lines: [{
        text: symbol || '',
        color: theme.watermark,
        fontSize: 52,
        fontStyle: 'bold',
        fontFamily: theme.font,
      }],
    })
    api.zones.setZones(findZones(bars, modelFromText(modelText)), bars)
    api.footprint.setBars(bars)
    showLatest(api.chart, bars.length)
  }, [bars, symbol])

  function jumpToLatest() {
    const api = apiRef.current
    if (!api || !barsRef.current.length) return
    showLatest(api.chart, barsRef.current.length)
  }

  return (
    <>
      <div ref={containerRef} className="chart" />
      {showJump && (
        <button type="button" className="jump" onClick={jumpToLatest} title="Go to latest bar">
          <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
            <path d="M5.5 3.5 10.5 8l-5 4.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      )}
    </>
  )
}
