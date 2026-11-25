/**
 * TradingView / Kite style long-position box.
 *
 * Draws:
 *   - green profit zone (entry → target)
 *   - red risk zone (entry → stop)
 *   - horizontal Entry / Stop / Target lines
 *   - square drag handles on the right edge
 *
 * Dragging itself is handled by ChartStage (pointer events → price).
 * This primitive only paints and exposes hit-testing helpers.
 */

import { formatPrice } from '../data/format'
import { LEFT_PAD } from './seriesData'

const FONT = "-apple-system, BlinkMacSystemFont, 'Trebuchet MS', Roboto, sans-serif"

const PROFIT_FILL = 'rgba(8, 153, 129, 0.10)'
const PROFIT_EDGE = 'rgba(8, 153, 129, 0.55)'
const RISK_FILL = 'rgba(242, 54, 69, 0.09)'
const RISK_EDGE = 'rgba(242, 54, 69, 0.55)'
const ENTRY_EDGE = 'rgba(41, 98, 255, 0.65)'
const HANDLE_FILL = '#2962ff'
const HANDLE_STROKE = '#ffffff'
const TEXT = '#131722'

/** How close (CSS pixels) the cursor must be to a level line (near the handle). */
export const HIT_DISTANCE_PX = 12

/** Visual size of each drag handle (CSS pixels). */
const HANDLE_SIZE_CSS = 8

/** Only the right-hand strip is draggable, so chart pans stay free. */
const HANDLE_HIT_LEFT_PAD_CSS = 28
const HANDLE_HIT_RIGHT_PAD_CSS = 18

function round(value) {
  return Math.round(value)
}

/** 1 device-pixel hairline (stays thin on retina). */
function hairline(pixelRatio) {
  return Math.max(1, Math.round(pixelRatio * 0.5) || 1)
}

function drawHandle(context, x, y, size, horizontal, vertical) {
  const half = (size * Math.min(horizontal, vertical)) / 2
  context.fillStyle = HANDLE_FILL
  context.strokeStyle = HANDLE_STROKE
  context.lineWidth = hairline(horizontal)
  context.beginPath()
  context.rect(x - half, y - half, half * 2, half * 2)
  context.fill()
  context.stroke()
}

function drawBand(context, left, right, yTop, yBottom, fill) {
  const top = Math.min(yTop, yBottom)
  const bottom = Math.max(yTop, yBottom)
  const height = Math.max(1, bottom - top)
  context.fillStyle = fill
  // Fill only — no strokeRect. Vertical borders were hiding candle wicks.
  context.fillRect(left, top, Math.max(1, right - left), height)
}

function drawLevelLine(context, left, right, y, color, pixelRatio) {
  const width = hairline(pixelRatio)
  context.strokeStyle = color
  context.lineWidth = width
  context.beginPath()
  // Align to half-pixel for a crisp thin horizontal.
  const yAligned = Math.round(y) + (width % 2 === 1 ? 0.5 : 0)
  context.moveTo(left, yAligned)
  context.lineTo(right, yAligned)
  context.stroke()
}

function rewardRisk(entry, stop, target) {
  const risk = entry - stop
  const reward = target - entry
  if (!(risk > 0) || !(reward > 0)) return null
  return reward / risk
}

class LongPositionRenderer {
  constructor(source) {
    this.source = source
  }

  draw(target) {
    const { chart, series, position } = this.source
    if (!chart || !series || !position) return

    const entry = position.entry
    const stop = position.stop
    const targetPrice = position.target
    if (![entry, stop, targetPrice].every(Number.isFinite)) return
    if (!(stop < entry && entry < targetPrice)) return

    target.useBitmapCoordinateSpace((scope) => {
      const context = scope.context
      const horizontal = scope.horizontalPixelRatio
      const vertical = scope.verticalPixelRatio

      const x1 = chart.timeScale().logicalToCoordinate(LEFT_PAD + position.from)
      const x2 = chart.timeScale().logicalToCoordinate(LEFT_PAD + position.to)
      const yEntry = series.priceToCoordinate(entry)
      const yStop = series.priceToCoordinate(stop)
      const yTarget = series.priceToCoordinate(targetPrice)
      if (x1 == null || x2 == null || yEntry == null || yStop == null || yTarget == null) return

      const left = round(Math.min(x1, x2) * horizontal)
      const right = round(Math.max(x1, x2) * horizontal)
      const entryY = round(yEntry * vertical)
      const stopY = round(yStop * vertical)
      const targetY = round(yTarget * vertical)

      // Profit (above entry) and risk (below entry) bands — soft fill, no box border.
      drawBand(context, left, right, entryY, targetY, PROFIT_FILL)
      drawBand(context, left, right, entryY, stopY, RISK_FILL)

      // Thin horizontal Entry / Stop / Target lines only (no heavy vertical edge).
      drawLevelLine(context, left, right, targetY, PROFIT_EDGE, horizontal)
      drawLevelLine(context, left, right, entryY, ENTRY_EDGE, horizontal)
      drawLevelLine(context, left, right, stopY, RISK_EDGE, horizontal)

      // Drag handles on the right edge.
      const handle = HANDLE_SIZE_CSS
      drawHandle(context, right, targetY, handle, horizontal, vertical)
      drawHandle(context, right, entryY, handle, horizontal, vertical)
      drawHandle(context, right, stopY, handle, horizontal, vertical)

      // Labels.
      const rr = rewardRisk(entry, stop, targetPrice)
      const pad = round(8 * horizontal)
      context.font = `600 ${Math.round(11 * vertical)}px ${FONT}`
      context.textBaseline = 'middle'
      context.fillStyle = TEXT

      const targetPct = ((targetPrice - entry) / entry) * 100
      const stopPct = ((entry - stop) / entry) * 100
      context.fillStyle = PROFIT_EDGE
      context.fillText(
        `Target ${formatPrice(targetPrice)}  (${targetPct.toFixed(2)}%)`,
        left + pad,
        targetY - round(10 * vertical),
      )
      context.fillStyle = RISK_EDGE
      context.fillText(
        `Stop ${formatPrice(stop)}  (${stopPct.toFixed(2)}%)`,
        left + pad,
        stopY + round(10 * vertical),
      )
      context.fillStyle = ENTRY_EDGE
      context.fillText(
        `Entry ${formatPrice(entry)}${rr != null ? `  ·  R:R ${rr.toFixed(2)}` : ''}`,
        left + pad,
        entryY - round(10 * vertical),
      )
    })
  }
}

class LongPositionPaneView {
  constructor(source) {
    this.source = source
    this.paneRenderer = new LongPositionRenderer(source)
  }

  // Under candles so wicks/legs stay readable through the green/red fills.
  zOrder() {
    return 'bottom'
  }

  renderer() {
    return this.paneRenderer
  }
}

export class LongPositionPrimitive {
  constructor() {
    this.position = null
    this.chart = null
    this.series = null
    this.requestUpdate = () => {}
    this.view = new LongPositionPaneView(this)
  }

  attached({ chart, series, requestUpdate }) {
    this.chart = chart
    this.series = series
    this.requestUpdate = requestUpdate
  }

  detached() {
    this.chart = null
    this.series = null
    this.position = null
  }

  /**
   * @param {{ from: number, to: number, entry: number, stop: number, target: number } | null} position
   */
  setPosition(position) {
    this.position = position
    this.requestUpdate()
  }

  clear() {
    this.position = null
    this.requestUpdate()
  }

  /**
   * Which level is under the cursor (CSS coordinates relative to the pane).
   * Returns 'entry' | 'stop' | 'target' | null.
   *
   * Hits are limited to the right-edge handle strip so dragging the rest of
   * the chart still pans/zooms normally.
   */
  hitTest(cssX, cssY) {
    const { chart, series, position } = this
    if (!chart || !series || !position) return null
    if (![position.entry, position.stop, position.target].every(Number.isFinite)) return null

    const x1 = chart.timeScale().logicalToCoordinate(LEFT_PAD + position.from)
    const x2 = chart.timeScale().logicalToCoordinate(LEFT_PAD + position.to)
    if (x1 == null || x2 == null) return null

    const boxRight = Math.max(x1, x2)
    const handleLeft = boxRight - HANDLE_HIT_LEFT_PAD_CSS
    const handleRight = boxRight + HANDLE_HIT_RIGHT_PAD_CSS
    if (cssX < handleLeft || cssX > handleRight) return null

    const candidates = [
      { key: 'target', y: series.priceToCoordinate(position.target) },
      { key: 'entry', y: series.priceToCoordinate(position.entry) },
      { key: 'stop', y: series.priceToCoordinate(position.stop) },
    ]

    let best = null
    let bestDistance = HIT_DISTANCE_PX
    for (const item of candidates) {
      if (item.y == null) continue
      const distance = Math.abs(item.y - cssY)
      if (distance <= bestDistance) {
        bestDistance = distance
        best = item.key
      }
    }
    return best
  }

  /**
   * Convert a CSS Y inside the pane to a price on the candle series.
   */
  priceAtCssY(cssY) {
    if (!this.series) return null
    const price = this.series.coordinateToPrice(cssY)
    return Number.isFinite(price) ? price : null
  }

  updateAllViews() {}

  paneViews() {
    return [this.view]
  }
}
