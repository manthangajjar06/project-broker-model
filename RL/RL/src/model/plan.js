// The one entry, stop, and target. Same rules as RL/entry.py and §15.

const PRICE_GAP = 1e-6
const WICK_GAP = 1e-9
const DATR_BUFFER = 0.10
const ACCEPT_AT = 0.55
const ENTRY_ON_SESSION = 6

export function planFor(bars, zone) {
  if (!(zone.probability >= ACCEPT_AT)) return null
  const lastBar = bars[bars.length - 1]
  if (!lastBar || !entryIsDue(bars, zone, lastBar.date)) return null

  const legIn = bars[zone.start]
  const uoc = bars[zone.start + 1]
  const legOut = bars[zone.start + 2]
  const last = bars[zone.end]
  if (!legIn || !uoc || !legOut || !last) return null
  if (blocked(zone.patternType, legIn)) return null

  const datr = uoc.datr
  if (datr == null || !Number.isFinite(datr) || datr <= 0) return null
  const buffer = DATR_BUFFER * datr
  const entry = entryPrice(uoc, legOut, buffer)
  if (entry == null) return null

  return {
    entry,
    stop: stopPrice(zone.patternType, legIn, uoc, buffer),
    target: last.close,
  }
}

export function entryIsDue(bars, zone, onDate) {
  const signal = bars[zone.end].date
  if (onDate < signal) return false
  let count = 0
  let previous = null
  for (const bar of bars) {
    if (bar.date < signal) continue
    if (bar.date > onDate) break
    if (bar.date !== previous) {
      count += 1
      previous = bar.date
    }
    if (count >= ENTRY_ON_SESSION) return true
  }
  return false
}

function blocked(pattern, legIn) {
  if (pattern === 'DBR') return samePrice(legIn.low, legIn.close)
  if (pattern === 'RBR') return samePrice(legIn.high, legIn.close)
  return true
}

function entryPrice(uoc, legOut, buffer) {
  if (!(legOut.close > legOut.open)) return null
  const tailUnderTheOpen = legOut.low < legOut.open - WICK_GAP
  if (tailUnderTheOpen && upperWickReachesBody(uoc, legOut)) return legOut.low
  if (samePrice(legOut.open, legOut.low)) return legOut.open
  if (tailUnderTheOpen) {
    const anchor = uoc.close < uoc.open ? uoc.open : uoc.close
    return anchor + buffer
  }
  return null
}

function stopPrice(pattern, legIn, uoc, buffer) {
  let reference = uoc.low
  const legInHasLowerWick = legIn.low < Math.min(legIn.open, legIn.close) - WICK_GAP
  if (pattern === 'DBR' && legInHasLowerWick && legIn.low < uoc.low) reference = legIn.low
  return reference - buffer
}

function upperWickReachesBody(uoc, legOut) {
  const bodyTop = Math.max(uoc.open, uoc.close)
  if (!(uoc.high > bodyTop + WICK_GAP)) return false
  const bodyLow = Math.min(legOut.open, legOut.close)
  const bodyHigh = Math.max(legOut.open, legOut.close)
  return Math.max(bodyTop, bodyLow) <= Math.min(uoc.high, bodyHigh) + WICK_GAP
}

function samePrice(left, right) {
  return Math.abs(left - right) <= PRICE_GAP
}
