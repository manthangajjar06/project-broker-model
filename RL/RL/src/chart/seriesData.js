export const VISIBLE_BARS = 120
export const LEFT_PAD = 40
export const RIGHT_PAD = 8

const PAD_STEP = 2 * 60 * 60

export function linePoints(bars, key) {
  const points = []
  for (const bar of bars) {
    const value = bar[key]
    if (value == null) continue
    points.push({ time: bar.time, value })
  }
  return points
}

export function candleData(bars) {
  const first = bars[0].time
  const last = bars[bars.length - 1].time
  const data = []
  for (let i = LEFT_PAD; i >= 1; i -= 1) data.push({ time: first - i * PAD_STEP })
  for (const bar of bars) {
    data.push({
      time: bar.time,
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
    })
  }
  for (let i = 1; i <= RIGHT_PAD; i += 1) data.push({ time: last + i * PAD_STEP })
  return data
}

export function showLatest(chart, count) {
  const lastIndex = LEFT_PAD + count + RIGHT_PAD - 1
  chart.timeScale().setVisibleLogicalRange({
    from: Math.max(lastIndex - VISIBLE_BARS, 0),
    to: lastIndex,
  })
}

export function showAround(chart, barIndex, count) {
  const center = LEFT_PAD + barIndex
  const half = Math.floor(VISIBLE_BARS / 2)
  const lastIndex = LEFT_PAD + count + RIGHT_PAD - 1
  chart.timeScale().setVisibleLogicalRange({
    from: Math.max(center - half, 0),
    to: Math.min(center + half, lastIndex),
  })
}

/**
 * Zoom the price scale to the candles around a bar, plus any Entry/Stop/Target.
 * Keeps autoScale on so the user can still pan the price axis afterward.
 */
export function fitPriceWindow(series, bars, barIndex, extraPrices = [], padBars = 30) {
  if (!series || !bars.length) return

  const start = Math.max(0, barIndex - padBars)
  const end = Math.min(bars.length - 1, barIndex + padBars)
  const prices = []

  for (let index = start; index <= end; index += 1) {
    const bar = bars[index]
    if (Number.isFinite(bar.high)) prices.push(bar.high)
    if (Number.isFinite(bar.low)) prices.push(bar.low)
  }
  for (const value of extraPrices) {
    if (Number.isFinite(value)) prices.push(value)
  }

  if (prices.length < 2) {
    series.priceScale().applyOptions({ autoScale: true })
    return
  }

  const lo = Math.min(...prices)
  const hi = Math.max(...prices)
  const span = Math.max(hi - lo, Math.abs(hi) * 0.01, 1)
  const pad = span * 0.18

  try {
    series.priceScale().setVisibleRange({
      from: lo - pad,
      to: hi + pad,
    })
  } catch {
    series.priceScale().applyOptions({ autoScale: true })
  }
}
