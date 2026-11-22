// IST wall-clock stored as UTC so the chart axis prints 09:15 instead of 03:45.
function wallClock(date, time) {
  const [year, month, day] = date.split('-').map(Number)
  const [hour, minute, second] = time.split(':').map(Number)
  if (![year, month, day, hour, minute].every(Number.isFinite)) return null
  return Math.floor(Date.UTC(year, month - 1, day, hour, minute, second || 0) / 1000)
}

function footprintLevels(text) {
  if (!text) return []
  const levels = []
  for (const part of text.split(';')) {
    const [priceText, sides] = part.split('=')
    const [buyText, sellText] = (sides ?? '').split('/')
    const price = Number(priceText)
    const buy = Number(buyText)
    const sell = Number(sellText)
    if (!Number.isFinite(price)) continue
    levels.push({
      price,
      buy: Number.isFinite(buy) ? buy : 0,
      sell: Number.isFinite(sell) ? sell : 0,
    })
  }
  levels.sort((a, b) => b.price - a.price)
  return levels
}

function columnValue(cells, index, key) {
  const raw = cells[index[key]]
  if (raw == null) return null
  const text = raw.trim()
  if (!text) return null
  const value = Number(text)
  return Number.isFinite(value) ? value : null
}

export function parseCsv(text) {
  const lines = text.split(/\r?\n/).filter((line) => line.trim())
  if (lines.length < 2) return []

  const header = lines[0].split(',').map((name) => name.trim())
  const index = Object.fromEntries(header.map((name, position) => [name, position]))
  const required = ['date', 'time', 'open', 'high', 'low', 'close']
  const missing = required.find((name) => index[name] == null)
  if (missing) throw new Error(`CSV is missing the ${missing} column`)

  const bars = []
  let previousTime = -1

  for (let lineNumber = 1; lineNumber < lines.length; lineNumber += 1) {
    const cells = lines[lineNumber].split(',')
    const date = cells[index.date]?.trim() ?? ''
    const clock = cells[index.time]?.trim() ?? ''
    const open = columnValue(cells, index, 'open')
    const high = columnValue(cells, index, 'high')
    const low = columnValue(cells, index, 'low')
    const close = columnValue(cells, index, 'close')
    if (!date || !clock || open == null || high == null || low == null || close == null) continue

    let time = wallClock(date, clock)
    if (time == null) continue
    if (time <= previousTime) time = previousTime + 1
    previousTime = time

    bars.push({
      time,
      symbol: cells[index.symbol]?.trim() ?? '',
      interval: cells[index.interval]?.trim() ?? '',
      date,
      clock: clock.slice(0, 5),
      open,
      high,
      low,
      close,
      volume: columnValue(cells, index, 'volume'),
      upperWick: columnValue(cells, index, 'upper_wick_pct'),
      lowerWick: columnValue(cells, index, 'lower_wick_pct'),
      body: columnValue(cells, index, 'body_pct'),
      tr: columnValue(cells, index, 'tr'),
      atr: columnValue(cells, index, 'atr_14'),
      datr: columnValue(cells, index, 'datr_14'),
      avgVolume: columnValue(cells, index, 'avg_volume_14d'),
      ema20: columnValue(cells, index, 'ema_20'),
      ema50: columnValue(cells, index, 'ema_50'),
      buyVolume: columnValue(cells, index, 'buy_volume'),
      sellVolume: columnValue(cells, index, 'sell_volume'),
      delta: columnValue(cells, index, 'delta'),
      footprint: footprintLevels(cells[index.footprint]?.trim() ?? ''),
    })
  }

  return bars
}
