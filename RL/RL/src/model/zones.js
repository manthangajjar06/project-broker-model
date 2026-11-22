import { loadModel, predictProbability, scoreLabel } from './predict.js'

const CODES = {
  pattern_type: { DBR: 0, RBR: 1 },
  leg_out_mode: { SINGLE: 0, SUPER: 1 },
  boring_color: { Green: 0, Red: 1 },
}

const EPS = 1e-9

function body(candle) {
  return Math.abs(candle.close - candle.open)
}

function isRed(candle) {
  if (candle.close >= candle.open) return false
  const range = candle.high - candle.low
  return range > 0 && (candle.open - candle.close) / range >= 0.55
}

function isGreen(candle) {
  if (candle.close <= candle.open) return false
  const range = candle.high - candle.low
  return range > 0 && (candle.close - candle.open) / range >= 0.55
}

function isBoring(candle, legBody) {
  return body(candle) < 0.45 * legBody
}

function gapAndOverlap(boringTop, boringBody, legOutOpen) {
  const hasGap = legOutOpen > boringTop
  const overlap = Math.max(0, boringTop - legOutOpen)
  return {
    hasGap,
    effectiveOpen: hasGap ? boringTop : legOutOpen,
    gapSize: Math.max(0, legOutOpen - boringTop),
    penetrationPct: boringBody > 0 ? (overlap / boringBody) * 100 : null,
  }
}

function round(value, digits) {
  const factor = 10 ** digits
  return Math.round(value * factor) / factor
}

function candidate(kind, mode, start, end, metrics) {
  const legMode = mode.includes('SUPER') ? 'SUPER' : 'SINGLE'
  return {
    patternType: kind,
    legOutMode: legMode,
    start,
    end,
    metrics: {
      legInBody: round(metrics.legInBody, 2),
      boringBody: round(metrics.boringBody, 2),
      boringRatioPct: round(metrics.boringPct, 1),
      boringColor: metrics.boringGreen ? 'Green' : 'Red',
      hasGap: metrics.hasGap,
      gapSize: round(metrics.gapSize, 2),
      adjustedLegOutBody: round(metrics.adjustedBody, 2),
      penetrationPct: metrics.penetrationPct == null ? null : round(metrics.penetrationPct, 1),
      rallyCandleCount: metrics.rallyCount,
    },
  }
}

function singleCandidates(bars) {
  const found = []
  for (let i = 0; i < bars.length - 2; i += 1) {
    const leg = bars[i]
    const base = bars[i + 1]
    const out = bars[i + 2]
    const setups = []
    if (isRed(leg)) setups.push('DBR')
    if (isGreen(leg)) setups.push('RBR')
    for (const kind of setups) {
      if (leg.date !== base.date) continue
      const legBody = kind === 'DBR' ? leg.open - leg.close : leg.close - leg.open
      if (!isBoring(base, legBody)) continue
      if (out.close <= out.open) continue
      const rawBody = out.close - out.open
      const rawRange = out.high - out.low
      if (rawRange <= 0 || rawBody < rawRange - rawBody) continue
      if (kind === 'DBR' && out.open > leg.open) continue
      if (out.open < base.low) continue
      const baseBody = body(base)
      const boringGreen = base.close >= base.open
      const boringTop = boringGreen ? base.close : base.open
      const gap = gapAndOverlap(boringTop, baseBody, out.open)
      if (!(rawRange > 0 && rawBody / rawRange >= 0.55)) continue
      const adjusted = out.close - gap.effectiveOpen
      if (!(adjusted > legBody && adjusted > baseBody)) continue
      found.push(candidate(kind, 'SINGLE (1 Candle)', i, i + 2, {
        legInBody: legBody,
        boringBody: baseBody,
        boringPct: legBody ? (baseBody / legBody) * 100 : 0,
        boringGreen,
        hasGap: gap.hasGap,
        gapSize: gap.gapSize,
        penetrationPct: gap.penetrationPct,
        adjustedBody: adjusted,
        rallyCount: 1,
      }))
    }
  }
  return found
}

function superCandidates(bars) {
  const found = []
  for (let i = 0; i < bars.length - 4; i += 1) {
    const one = bars[i]
    const base = bars[i + 1]
    const three = bars[i + 2]
    const four = bars[i + 3]
    const five = bars[i + 4]
    const setups = []
    if (isRed(one)) setups.push('DBR')
    if (isGreen(one)) setups.push('RBR')
    for (const kind of setups) {
      if (one.date !== base.date) continue
      const legBody = Math.abs(one.close - one.open)
      if (!isBoring(base, legBody) || three.close <= three.open) continue
      const rawBody = three.close - three.open
      const rawRange = three.high - three.low
      if (rawRange <= 0 || rawBody < rawRange - rawBody || three.open < base.low) continue
      if (kind === 'DBR' && three.open > one.open) continue
      if (four.close < four.open || five.close < five.open) continue
      if (!(four.close > four.open || five.close > five.open)) continue
      const baseBody = body(base)
      const boringGreen = base.close >= base.open
      const baseTop = boringGreen ? base.close : base.open
      const gap = gapAndOverlap(baseTop, baseBody, three.open)
      const superBody = five.close - gap.effectiveOpen
      const superRange = Math.max(three.high, four.high, five.high) - Math.min(three.low, four.low, five.low, gap.effectiveOpen)
      const superWick = superRange - superBody
      if (!(superBody > superWick && superBody > legBody && superBody > baseBody)) continue
      found.push(candidate(kind, 'SUPER (3 Candles)', i, i + 4, {
        legInBody: legBody,
        boringBody: baseBody,
        boringPct: legBody ? (baseBody / legBody) * 100 : 0,
        boringGreen,
        hasGap: gap.hasGap,
        gapSize: gap.gapSize,
        penetrationPct: gap.penetrationPct,
        adjustedBody: superBody,
        rallyCount: 3,
      }))
    }
  }
  return found
}

function trueRangeAndAtr(bars) {
  const tr = bars.map((bar, index) => {
    const span = bar.high - bar.low
    if (index === 0) return span
    const previous = bars[index - 1].close
    return Math.max(span, Math.abs(bar.high - previous), Math.abs(bar.low - previous))
  })
  const atr = new Array(bars.length).fill(0)
  const length = 14
  if (bars.length >= length) {
    for (let i = 0; i < length - 1; i += 1) {
      let sum = 0
      for (let j = 0; j <= i; j += 1) sum += tr[j]
      atr[i] = sum / (i + 1)
    }
    let seed = 0
    for (let i = 0; i < length; i += 1) seed += tr[i]
    atr[length - 1] = seed / length
    for (let i = length; i < bars.length; i += 1) atr[i] = (atr[i - 1] * (length - 1) + tr[i]) / length
  } else {
    for (let i = 0; i < bars.length; i += 1) {
      let sum = 0
      for (let j = 0; j <= i; j += 1) sum += tr[j]
      atr[i] = sum / (i + 1)
    }
  }
  return { tr, atr }
}

function weekday(date) {
  const [year, month, day] = date.split('-').map(Number)
  return (new Date(Date.UTC(year, month - 1, day)).getUTCDay() + 6) % 7
}

function dailyAtr(bars) {
  const days = []
  for (const bar of bars) {
    const last = days[days.length - 1]
    if (!last || last.date !== bar.date) days.push({ date: bar.date, high: bar.high, low: bar.low, close: bar.close })
    else {
      last.high = Math.max(last.high, bar.high)
      last.low = Math.min(last.low, bar.low)
      last.close = bar.close
    }
  }
  const tr = days.map((day, index) => {
    const span = day.high - day.low
    if (index === 0) return span
    const previous = days[index - 1].close
    return Math.max(span, Math.abs(day.high - previous), Math.abs(day.low - previous))
  })
  const alpha = 1 / 14
  const smoothed = []
  let value = null
  for (let i = 0; i < tr.length; i += 1) {
    value = value == null ? tr[i] : value * (1 - alpha) + tr[i] * alpha
    smoothed.push(i >= 13 ? value : null)
  }
  const byDate = new Map()
  for (let i = 1; i < days.length; i += 1) {
    if (smoothed[i - 1] != null) byDate.set(days[i].date, smoothed[i - 1])
  }
  return byDate
}

function entryPrice(base, legOut, datr) {
  const legOpen = legOut.open
  const legClose = legOut.close
  const lowerWick = legOut.low < Math.min(legOpen, legClose) - EPS
  const upperWick = base.high > Math.max(base.open, base.close) + EPS
  const overlap = Math.max(Math.min(legOpen, legClose), base.low) <= Math.min(Math.max(legOpen, legClose), base.high) + EPS
  if (!lowerWick) return { price: legOpen, warning: false }
  if (!overlap) return { price: base.high, warning: false }
  if (!upperWick) return { price: legOpen, warning: false }
  const red = base.close < base.open
  const anchor = red ? base.open : base.close
  if (datr == null || !Number.isFinite(datr) || datr <= 0) return { price: anchor, warning: true }
  return { price: anchor + 0.1 * datr, warning: false }
}

function ratio(part, whole) {
  return whole ? part / whole : 0
}

function featuresFor(bars, zone, tr, atr) {
  const slice = bars.slice(zone.start, zone.end + 1)
  const metrics = zone.metrics
  const first = slice[0]
  const second = slice[1]
  const last = slice[slice.length - 1]
  const zoneHigh = Math.max(...slice.map((bar) => bar.high))
  const zoneLow = Math.min(...slice.map((bar) => bar.low))
  const zoneRange = zoneHigh - zoneLow
  const zoneOpen = first.open
  const zoneBody = Math.abs(last.close - zoneOpen)
  const totalVolume = slice.reduce((sum, bar) => sum + (bar.volume ?? 0), 0)
  const averageVolume = slice.length ? totalVolume / slice.length : 0
  const firstRange = first.high - first.low
  const secondRange = second.high - second.low
  const lastRange = last.high - last.low
  const rally = slice.slice(2).map((bar) => ratio(body(bar), bar.high - bar.low))
  const atrStart = atr[zone.start]
  const atrEnd = atr[zone.end]
  const number = (value) => (value == null || Number.isNaN(value) ? Number.NaN : value)
  return [
    CODES.pattern_type[zone.patternType],
    CODES.leg_out_mode[zone.legOutMode],
    CODES.boring_color[metrics.boringColor],
    metrics.rallyCandleCount,
    metrics.boringRatioPct,
    metrics.hasGap ? 1 : 0,
    number(metrics.penetrationPct),
    atrStart ? tr[zone.start] / atrStart : Number.NaN,
    atrEnd ? tr[zone.end] / atrEnd : Number.NaN,
    slice.length,
    ratio(zoneBody, zoneRange),
    lastRange > 0 ? body(last) / lastRange : 0,
    lastRange > 0 ? (last.high - Math.max(last.open, last.close)) / lastRange : 0,
    lastRange > 0 ? (Math.min(last.open, last.close) - last.low) / lastRange : 0,
    lastRange > 0 ? (last.close - last.low) / lastRange : 0.5,
    averageVolume > 0 ? (last.volume ?? 0) / averageVolume : 1,
    rally.length ? Math.min(...rally) : 0,
    firstRange > 0 ? (firstRange - body(first)) / firstRange : 0,
    firstRange > 0 ? (first.close - first.low) / firstRange : 0.5,
    secondRange > 0 ? (secondRange - body(second)) / secondRange : 0,
    zoneOpen ? (zoneHigh - zoneLow) / zoneOpen : Number.NaN,
    zoneOpen ? metrics.legInBody / zoneOpen : Number.NaN,
    zoneOpen ? metrics.gapSize / zoneOpen : Number.NaN,
    zoneOpen ? metrics.adjustedLegOutBody / zoneOpen : Number.NaN,
    totalVolume > 0 ? (last.volume ?? 0) / totalVolume : 1 / slice.length,
    Number(last.clock.slice(0, 2)),
    weekday(last.date),
    atrStart ? atrEnd / atrStart : Number.NaN,
    metrics.legInBody ? metrics.boringBody / metrics.legInBody : Number.NaN,
    (metrics.legInBody + metrics.boringBody) ? metrics.adjustedLegOutBody / (metrics.legInBody + metrics.boringBody) : Number.NaN,
    metrics.legInBody ? metrics.adjustedLegOutBody / metrics.legInBody : Number.NaN,
  ]
}

function buildZone(bars, zone, datrByDate) {
  const base = bars[zone.start + 1]
  const legOut = bars[zone.start + 2]
  const low = base.low
  const high = base.high
  let touch = bars.length - 1
  let status = 'fresh'
  for (let index = zone.end + 1; index < bars.length; index += 1) {
    const bar = bars[index]
    if (bar.low <= high + EPS && bar.high >= low - EPS) {
      touch = index
      status = 'worked'
      break
    }
  }
  const entry = entryPrice(base, legOut, datrByDate.get(base.date))
  const marker = bars[zone.end]
  return {
    ...zone,
    low,
    high,
    entry: entry.price,
    warning: entry.warning,
    status,
    from: zone.start + 1,
    to: touch,
    markerIndex: zone.end,
    markerLow: marker.low,
    markerHigh: marker.high,
  }
}

export function findZones(bars, model) {
  if (bars.length < 3 || !model) return []
  const { tr, atr } = trueRangeAndAtr(bars)
  const datrByDate = dailyAtr(bars)
  const seen = new Set()
  const candidates = []
  for (const zone of [...singleCandidates(bars), ...superCandidates(bars)]) {
    const key = `${zone.patternType}|${zone.start}|${zone.end}|${zone.legOutMode}`
    if (seen.has(key)) continue
    seen.add(key)
    candidates.push(zone)
  }
  return candidates.map((zone) => {
    const probability = predictProbability(model, featuresFor(bars, zone, tr, atr))
    const drawn = buildZone(bars, zone, datrByDate)
    return {
      ...drawn,
      probability,
      label: scoreLabel(probability),
    }
  })
}

let cachedModel = null

export function modelFromText(text) {
  if (!cachedModel) cachedModel = loadModel(text)
  return cachedModel
}
