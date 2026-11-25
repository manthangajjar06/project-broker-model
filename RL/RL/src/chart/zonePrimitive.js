import { formatPrice } from '../data/format'
import { planFor } from '../model/plan'
import { theme } from './theme'
import { LEFT_PAD } from './seriesData'

const LABEL_COLOR = {
  accepted: '#00E676',
  rejected: '#FF1744',
  uncertain: '#FFB300',
}

const UOC_COLOR = '#e65100'

const FONT = "-apple-system, BlinkMacSystemFont, 'Trebuchet MS', Roboto, sans-serif"

const LEVELS = [
  { key: 'entry', label: 'Entry', color: theme.ema20 },
  { key: 'stop', label: 'Stop', color: theme.down },
  { key: 'target', label: 'Target', color: theme.up },
]

function caption(zone) {
  const accepted = Math.round(zone.probability * 100)
  const word = zone.label === 'rejected' ? 'Rejected' : zone.label === 'uncertain' ? 'Unsure' : 'Accepted'
  const percent = zone.label === 'rejected' ? 100 - accepted : accepted
  return `${zone.patternType} ${word} ${percent}%`
}

function markersFrom(zones) {
  const byBase = new Map()
  for (const zone of zones) {
    const key = `${zone.patternType}:${zone.start}`
    const current = byBase.get(key)
    if (!current || zone.probability > current.probability || (zone.probability === current.probability && zone.legOutMode === 'SUPER')) {
      byBase.set(key, zone)
    }
  }
  return [...byBase.values()].map((zone) => {
    const down = zone.label === 'rejected'
    return {
      index: zone.markerIndex,
      price: down ? zone.markerHigh : zone.markerLow,
      down,
      text: caption(zone),
      color: LABEL_COLOR[zone.label] || LABEL_COLOR.uncertain,
    }
  })
}

/** One marker under each zone's UOC (base) candle. */
function uocMarkersFrom(zones) {
  const byBase = new Map()
  for (const zone of zones) {
    const key = `${zone.patternType}:${zone.start}`
    const current = byBase.get(key)
    if (!current || zone.probability > current.probability || (zone.probability === current.probability && zone.legOutMode === 'SUPER')) {
      byBase.set(key, zone)
    }
  }
  return [...byBase.values()].map((zone) => ({
    index: zone.start + 1,
    price: zone.low,
    text: 'UOC',
    color: UOC_COLOR,
  }))
}

function levelsFrom(zones, bars) {
  const byBase = new Map()
  for (const zone of zones) {
    const key = `${zone.patternType}:${zone.start}`
    const current = byBase.get(key)
    if (!current || zone.probability > current.probability || (zone.probability === current.probability && zone.legOutMode === 'SUPER')) {
      byBase.set(key, zone)
    }
  }
  const levels = []
  for (const zone of byBase.values()) {
    const plan = planFor(bars, zone)
    if (!plan) continue
    levels.push({
      from: zone.start,
      to: zone.end,
      entry: plan.entry,
      stop: plan.stop,
      target: plan.target,
    })
  }
  return levels
}

function drawLevels(context, chart, series, levels, horizontal, vertical) {
  context.save()
  context.font = `600 ${Math.round(11 * vertical)}px ${FONT}`
  context.textBaseline = 'middle'
  context.lineWidth = Math.max(1, Math.round(horizontal))
  for (const level of levels) {
    const x1 = chart.timeScale().logicalToCoordinate(LEFT_PAD + level.from)
    const x2 = chart.timeScale().logicalToCoordinate(LEFT_PAD + level.to)
    if (x1 == null || x2 == null) continue
    const left = Math.round(Math.min(x1, x2) * horizontal)
    const right = Math.round(Math.max(x1, x2) * horizontal)
    for (const item of LEVELS) {
      const yCss = series.priceToCoordinate(level[item.key])
      if (yCss == null) continue
      const y = Math.round(yCss * vertical)
      context.strokeStyle = item.color
      context.beginPath()
      context.moveTo(left, y)
      context.lineTo(right, y)
      context.stroke()
      context.fillStyle = item.color
      context.fillText(`${item.label} ${formatPrice(level[item.key])}`, right + Math.round(4 * horizontal), y)
    }
  }
  context.restore()
}

function drawArrow(context, x, y, down, color, size) {
  context.fillStyle = color
  context.beginPath()
  if (down) {
    context.moveTo(x, y + size)
    context.lineTo(x - size * 0.72, y - size * 0.35)
    context.lineTo(x + size * 0.72, y - size * 0.35)
  } else {
    context.moveTo(x, y - size)
    context.lineTo(x - size * 0.72, y + size * 0.45)
    context.lineTo(x + size * 0.72, y + size * 0.45)
  }
  context.closePath()
  context.fill()
}

/** Small upward arrow + "UOC" label parked under the base candle low. */
function drawUocMarkers(context, chart, series, markers, horizontal, vertical) {
  if (!markers.length) return
  const size = Math.max(7, Math.round(8 * vertical))
  context.save()
  context.font = `700 ${Math.round(11 * vertical)}px ${FONT}`
  context.textBaseline = 'top'
  for (const marker of markers) {
    const xCss = chart.timeScale().logicalToCoordinate(LEFT_PAD + marker.index)
    const yCss = series.priceToCoordinate(marker.price)
    if (xCss == null || yCss == null) continue
    const x = Math.round(xCss * horizontal)
    const y = Math.round(yCss * vertical) + Math.round(4 * vertical)
    drawArrow(context, x, y + size, false, marker.color, size)
    context.fillStyle = marker.color
    context.fillText(marker.text || 'UOC', x - Math.round(12 * horizontal), y + size * 2 + Math.round(2 * vertical))
  }
  context.restore()
}

class ZoneRenderer {
  constructor(source) {
    this.source = source
  }

  draw(target) {
    const { chart, series, markers, levels, uocMarkers } = this.source
    if (!chart || !series || (!markers.length && !levels.length && !uocMarkers.length)) return
    target.useBitmapCoordinateSpace((scope) => {
      const context = scope.context
      const horizontal = scope.horizontalPixelRatio
      const vertical = scope.verticalPixelRatio
      drawLevels(context, chart, series, levels, horizontal, vertical)
      drawUocMarkers(context, chart, series, uocMarkers, horizontal, vertical)
      const size = Math.max(6, Math.round(7 * vertical))
      context.font = `600 ${Math.round(12 * vertical)}px ${FONT}`
      context.textBaseline = 'middle'
      for (const marker of markers) {
        const xCss = chart.timeScale().logicalToCoordinate(LEFT_PAD + marker.index)
        const yCss = series.priceToCoordinate(marker.price)
        if (xCss == null || yCss == null) continue
        const x = Math.round(xCss * horizontal)
        const y = Math.round(yCss * vertical) + (marker.down ? -size - 2 : size + 2)
        drawArrow(context, x, y, marker.down, marker.color, size)
        context.fillStyle = marker.color
        context.fillText(marker.text, x + size + Math.round(4 * horizontal), y)
      }
    })
  }
}

class ZonePaneView {
  constructor(source) {
    this.source = source
    this.paneRenderer = new ZoneRenderer(source)
  }

  zOrder() {
    return 'top'
  }

  renderer() {
    return this.paneRenderer
  }
}

export class ZonePrimitive {
  constructor() {
    this.markers = []
    this.uocMarkers = []
    this.levels = []
    this.chart = null
    this.series = null
    this.requestUpdate = () => {}
    this.view = new ZonePaneView(this)
  }

  attached({ chart, series, requestUpdate }) {
    this.chart = chart
    this.series = series
    this.requestUpdate = requestUpdate
  }

  detached() {
    this.chart = null
    this.series = null
  }

  setZones(zones, bars = []) {
    this.markers = markersFrom(zones)
    this.uocMarkers = uocMarkersFrom(zones)
    this.levels = levelsFrom(zones, bars)
    this.requestUpdate()
  }

  /** One Plan-2 outcome row: entry / stop / target from the dataset. */
  setReviewLevel(level) {
    this.markers = []
    this.uocMarkers = []
    this.levels = level ? [level] : []
    this.requestUpdate()
  }

  /**
   * Label mode: clear accept/reject arrows, keep a single UOC marker
   * under the base candle of the zone being labeled.
   */
  setLabelUoc(marker) {
    this.markers = []
    this.levels = []
    this.uocMarkers = marker ? [marker] : []
    this.requestUpdate()
  }

  clearOverlays() {
    this.markers = []
    this.uocMarkers = []
    this.levels = []
    this.requestUpdate()
  }

  updateAllViews() {}

  paneViews() {
    return [this.view]
  }
}
