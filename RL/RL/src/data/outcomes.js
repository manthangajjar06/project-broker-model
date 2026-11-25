/** Slim Plan-2 outcome rows for chart review (`public/outcomes.json`). */

export async function loadOutcomes(signal) {
  const response = await fetch('/outcomes.json', { signal })
  if (!response.ok) throw new Error('Could not load outcomes.json')
  const rows = await response.json()
  if (!Array.isArray(rows)) throw new Error('outcomes.json is not a list')
  return rows
}

export function outcomesForSymbol(rows, symbol) {
  if (!symbol) return []
  const key = String(symbol).toUpperCase()
  return rows.filter((row) => String(row.symbol).toUpperCase() === key)
}

/** Match dataset decided_at ("YYYY-MM-DD HH:MM:SS") to a 2-hour bar index. */
export function barIndexAt(bars, decidedAt) {
  if (!bars?.length || !decidedAt) return -1
  const [datePart, timePart = '00:00:00'] = String(decidedAt).trim().split(/\s+/)
  const clock = timePart.slice(0, 5)
  const exact = bars.findIndex((bar) => bar.date === datePart && bar.clock === clock)
  if (exact >= 0) return exact
  return bars.findIndex((bar) => bar.date === datePart)
}

export function reviewLevelFrom(row, bars) {
  const from = barIndexAt(bars, row.decided_at)
  if (from < 0) return null
  let to = barIndexAt(bars, row.resolved_at)
  if (to < from) to = Math.min(from + 40, bars.length - 1)
  return {
    from,
    to,
    entry: row.entry,
    stop: row.stop,
    target: row.target,
  }
}
