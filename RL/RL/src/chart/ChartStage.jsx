import { useLayoutEffect, useRef, useState } from 'react'
import modelText from '../model/model.txt?raw'
import { findZones, modelFromText } from '../model/zones.js'
import { reviewLevelFrom } from '../data/outcomes'
import { createPriceChart, restoreChartInteraction } from './createPriceChart'
import { FootprintPrimitive } from './footprintPrimitive'
import { LongPositionPrimitive } from './longPositionPrimitive'
import {
  LEFT_PAD,
  candleData,
  fitPriceWindow,
  linePoints,
  showAround,
  showLatest,
} from './seriesData'
import { ZonePrimitive } from './zonePrimitive'
import { theme } from './theme'

/**
 * Keep stop < entry < target while the user drags one side.
 */
function constrainDrag(field, price, current) {
  const entry = current.entry
  const stop = current.stop
  const target = current.target
  const gap = Math.max(Math.abs(entry) * 1e-6, 0.01)

  if (field === 'entry') {
    const nextEntry = Math.min(Math.max(price, stop + gap), target - gap)
    return { entry: nextEntry, stop, target }
  }
  if (field === 'stop') {
    const nextStop = Math.min(price, entry - gap)
    return { entry, stop: nextStop, target }
  }
  if (field === 'target') {
    const nextTarget = Math.max(price, entry + gap)
    return { entry, stop, target: nextTarget }
  }
  return current
}

function zoneFocusKey(labelLevel) {
  if (!labelLevel) return null
  const focus = Number.isFinite(labelLevel.focus) ? labelLevel.focus : labelLevel.from
  if (!Number.isFinite(focus)) return null
  return `${focus}|${labelLevel.from}|${labelLevel.to}|${labelLevel.zoneKey || ''}`
}

function focusBarIndex(labelLevel) {
  if (!labelLevel) return null
  if (Number.isFinite(labelLevel.focus)) return labelLevel.focus
  if (Number.isFinite(labelLevel.from)) return labelLevel.from
  return null
}

export default function ChartStage({
  bars,
  symbol,
  reviewRow,
  labelLevel,
  onIndexChange,
  onLabelPricesChange,
}) {
  const containerRef = useRef(null)
  const apiRef = useRef(null)
  const barsRef = useRef(bars)
  const onIndexRef = useRef(onIndexChange)
  const onPricesRef = useRef(onLabelPricesChange)
  const labelLevelRef = useRef(labelLevel)
  const indexByTimeRef = useRef(new Map())
  const lastFocusKeyRef = useRef(null)
  const lastUocKeyRef = useRef(null)
  const lastBarsSymbolRef = useRef('')
  const dragRef = useRef(null)
  const [showJump, setShowJump] = useState(false)
  const [dragCursor, setDragCursor] = useState('')

  useLayoutEffect(() => {
    barsRef.current = bars
    onIndexRef.current = onIndexChange
    onPricesRef.current = onLabelPricesChange
    labelLevelRef.current = labelLevel
    const map = new Map()
    bars.forEach((bar, index) => map.set(bar.time, index))
    indexByTimeRef.current = map
  }, [bars, onIndexChange, onLabelPricesChange, labelLevel])

  useLayoutEffect(() => {
    const container = containerRef.current
    if (!container) return undefined

    const api = createPriceChart(container)
    const zones = new ZonePrimitive()
    const footprint = new FootprintPrimitive()
    const longPosition = new LongPositionPrimitive()
    api.candles.attachPrimitive(zones)
    api.candles.attachPrimitive(footprint)
    api.candles.attachPrimitive(longPosition)
    api.zones = zones
    api.footprint = footprint
    api.longPosition = longPosition

    /** End a drag without changing zoom / autoScale. */
    function endDragSoft(event) {
      const active = dragRef.current
      if (!active) return
      if (event && event.pointerId != null && active.pointerId !== event.pointerId) return
      try {
        if (event) container.releasePointerCapture(event.pointerId)
      } catch {
        // already released
      }
      dragRef.current = null
      setDragCursor('')
      restoreChartInteraction(api.chart)
    }

    api.chart.subscribeCrosshairMove((param) => {
      if (dragRef.current) return
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

    function panePoint(event) {
      const rect = container.getBoundingClientRect()
      return {
        x: event.clientX - rect.left,
        y: event.clientY - rect.top,
      }
    }

    function onPointerDown(event) {
      if (event.button !== 0) return
      const tool = api.longPosition
      const level = labelLevelRef.current
      if (!tool || !level) return
      if (![level.entry, level.stop, level.target].every(Number.isFinite)) return
      if (!(level.stop < level.entry && level.entry < level.target)) return

      const point = panePoint(event)
      const hit = tool.hitTest(point.x, point.y)
      if (!hit) return

      event.preventDefault()
      container.setPointerCapture(event.pointerId)
      dragRef.current = {
        field: hit,
        pointerId: event.pointerId,
        from: level.from,
        to: level.to,
        entry: level.entry,
        stop: level.stop,
        target: level.target,
      }
      setDragCursor('ns-resize')
      api.chart.applyOptions({
        handleScroll: false,
        handleScale: false,
      })
    }

    function onPointerMove(event) {
      const tool = api.longPosition
      if (!tool) return
      const point = panePoint(event)
      const active = dragRef.current

      if (!active) {
        const hit = tool.hitTest(point.x, point.y)
        const nextCursor = hit ? 'ns-resize' : ''
        setDragCursor((prev) => (prev === nextCursor ? prev : nextCursor))
        return
      }

      const price = tool.priceAtCssY(point.y)
      if (price == null) return

      const next = constrainDrag(active.field, price, {
        entry: active.entry,
        stop: active.stop,
        target: active.target,
      })

      active.entry = next.entry
      active.stop = next.stop
      active.target = next.target

      tool.setPosition({
        from: active.from,
        to: active.to,
        entry: next.entry,
        stop: next.stop,
        target: next.target,
      })

      if (typeof onPricesRef.current === 'function') {
        onPricesRef.current({
          entry: next.entry.toFixed(2),
          stop: next.stop.toFixed(2),
          target: next.target.toFixed(2),
        })
      }
    }

    function onKeyDown(event) {
      if (event.key === 'Escape') endDragSoft()
    }

    // Win+Shift+S / alt-tab fires window blur. Do NOT reset autoScale there.
    function onWindowBlur() {
      if (!dragRef.current) return
      dragRef.current = null
      setDragCursor('')
      restoreChartInteraction(api.chart)
    }

    container.addEventListener('pointerdown', onPointerDown)
    window.addEventListener('pointermove', onPointerMove)
    window.addEventListener('pointerup', endDragSoft)
    window.addEventListener('pointercancel', endDragSoft)
    window.addEventListener('blur', onWindowBlur)
    window.addEventListener('keydown', onKeyDown)

    apiRef.current = api
    restoreChartInteraction(api.chart)

    return () => {
      container.removeEventListener('pointerdown', onPointerDown)
      window.removeEventListener('pointermove', onPointerMove)
      window.removeEventListener('pointerup', endDragSoft)
      window.removeEventListener('pointercancel', endDragSoft)
      window.removeEventListener('blur', onWindowBlur)
      window.removeEventListener('keydown', onKeyDown)
      api.chart.remove()
      apiRef.current = null
    }
  }, [])

  // Load candle / EMA data only when the symbol or bar array changes.
  useLayoutEffect(() => {
    const api = apiRef.current
    if (!api || !bars.length) return

    const key = `${symbol}|${bars.length}|${bars[0]?.time}|${bars[bars.length - 1]?.time}`
    const dataChanged = lastBarsSymbolRef.current !== key
    lastBarsSymbolRef.current = key

    if (dataChanged) {
      api.candles.setData(candleData(bars))
      api.ema20.setData(linePoints(bars, 'ema20'))
      api.ema50.setData(linePoints(bars, 'ema50'))
      api.watermark.applyOptions({
        lines: [{
          text: symbol || '',
          color: 'rgba(19, 23, 34, 0.028)',
          fontSize: 36,
          fontStyle: 'bold',
          fontFamily: theme.font,
        }],
      })
      api.footprint.setBars([])
      lastFocusKeyRef.current = null
    }
  }, [bars, symbol])

  // Zone camera / UOC / long-position sync.
  // While dragging, the pointer handler owns the box — never clear it here.
  // While typing, keep the last valid box if prices are briefly invalid.
  useLayoutEffect(() => {
    const api = apiRef.current
    if (!api || !bars.length) return

    const inLabelMode = labelLevel && Number.isFinite(labelLevel.from)
    const hasLabelBox = inLabelMode
      && [labelLevel.entry, labelLevel.stop, labelLevel.target].every(Number.isFinite)
      && labelLevel.stop < labelLevel.entry
      && labelLevel.entry < labelLevel.target
    const dragging = Boolean(dragRef.current)

    if (inLabelMode) {
      const uocKey = `${labelLevel.zoneKey || ''}|${labelLevel.uocIndex}|${labelLevel.uocLow}`
      if (lastUocKeyRef.current !== uocKey) {
        lastUocKeyRef.current = uocKey
        if (Number.isFinite(labelLevel.uocIndex) && Number.isFinite(labelLevel.uocLow)) {
          api.zones.setLabelUoc({
            index: labelLevel.uocIndex,
            price: labelLevel.uocLow,
            text: 'UOC',
            color: '#e65100',
          })
        } else {
          api.zones.clearOverlays()
        }
      }

      const focusKey = zoneFocusKey(labelLevel)
      const focusAt = focusBarIndex(labelLevel)
      const zoneJustChanged = Boolean(focusKey) && lastFocusKeyRef.current !== focusKey

      // Drag path updates the primitive directly — do not clear or fight it.
      if (!dragging) {
        if (hasLabelBox) {
          api.longPosition.setPosition({
            from: labelLevel.from,
            to: labelLevel.to,
            entry: labelLevel.entry,
            stop: labelLevel.stop,
            target: labelLevel.target,
          })
        } else if (zoneJustChanged) {
          // New zone with no usable prices — drop the previous zone's box.
          api.longPosition.clear()
        }
        // Same zone + briefly invalid typed prices → keep last painted box.
      }

      if (zoneJustChanged && Number.isFinite(focusAt)) {
        lastFocusKeyRef.current = focusKey
        showAround(api.chart, focusAt, bars.length)
        fitPriceWindow(
          api.candles,
          bars,
          focusAt,
          hasLabelBox
            ? [labelLevel.entry, labelLevel.stop, labelLevel.target]
            : [],
        )
        onIndexRef.current(focusAt)
      }
      return
    }

    lastUocKeyRef.current = null

    if (reviewRow) {
      lastFocusKeyRef.current = null
      api.longPosition.clear()
      const level = reviewLevelFrom(reviewRow, bars)
      api.zones.setReviewLevel(level)
      if (level) {
        showAround(api.chart, level.from, bars.length)
        fitPriceWindow(api.candles, bars, level.from, [level.entry, level.stop, level.target])
        onIndexRef.current(level.from)
      }
      return
    }

    lastFocusKeyRef.current = null
    api.longPosition.clear()
    api.zones.setZones(findZones(bars, modelFromText(modelText)), bars)
    showLatest(api.chart, bars.length)
    api.candles.priceScale().applyOptions({ autoScale: true })
  }, [bars, symbol, reviewRow, labelLevel])

  function jumpToLatest() {
    const api = apiRef.current
    if (!api || !barsRef.current.length) return
    restoreChartInteraction(api.chart)
    showLatest(api.chart, barsRef.current.length)
    api.candles.priceScale().applyOptions({ autoScale: true })
  }

  return (
    <>
      <div
        ref={containerRef}
        className={`chart${dragCursor ? ' chart-dragging' : ''}`}
        style={dragCursor ? { cursor: dragCursor } : undefined}
      />
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
