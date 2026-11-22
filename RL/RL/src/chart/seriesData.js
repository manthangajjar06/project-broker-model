export const VISIBLE_BARS = 150
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
