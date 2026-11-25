/** Accepted zones that are past the 3-year company-age gate. */

import { companyIsOldEnough } from './companyAge'
import { lockedPlanPrices } from '../model/plan'
import { findZones, modelFromText } from '../model/zones'

const ACCEPT_AT = 0.55

/**
 * One zone per pattern + start (same rule as Python keep_one / chart markers).
 * Higher probability wins; SUPER wins ties.
 */
function keepOneAccepted(zones) {
  const chosen = new Map()
  const order = []
  for (const zone of zones) {
    const key = `${zone.patternType}:${zone.start}`
    const current = chosen.get(key)
    if (!current) {
      chosen.set(key, zone)
      order.push(key)
      continue
    }
    if (
      zone.probability > current.probability
      || (zone.probability === current.probability && zone.legOutMode === 'SUPER')
    ) {
      chosen.set(key, zone)
    }
  }
  return order.map((key) => chosen.get(key))
}

/** Guarantee stop < entry < target for drawable long-position prefs. */
function sanitizePlanPrices(entry, stop, target, zoneLow) {
  let nextEntry = Number.isFinite(entry) ? entry : null
  let nextStop = Number.isFinite(stop) ? stop : (Number.isFinite(zoneLow) ? zoneLow : null)
  let nextTarget = Number.isFinite(target) ? target : null

  if (nextEntry == null || nextStop == null) {
    return { entry: nextEntry, stop: nextStop, target: nextTarget }
  }

  if (!(nextStop < nextEntry)) {
    const gap = Math.max(Math.abs(nextStop) * 1e-4, 0.01)
    nextEntry = nextStop + gap
  }
  if (nextTarget == null || !(nextTarget > nextEntry)) {
    nextTarget = nextEntry + Math.max(nextEntry - nextStop, 0.01)
  }
  return { entry: nextEntry, stop: nextStop, target: nextTarget }
}

/**
 * Build the list the label UI walks through.
 * Only accepted zones on a company older than 3 years at the zone date.
 */
export function buildLabelableZones(bars, modelText) {
  if (!bars?.length || !modelText) return []

  const firstDate = bars[0].date
  const model = modelFromText(modelText)
  const scored = findZones(bars, model)
  const accepted = []

  for (const zone of scored) {
    if (!(zone.probability >= ACCEPT_AT)) continue
    const signal = bars[zone.end]
    if (!signal) continue
    if (!companyIsOldEnough(firstDate, signal.date)) continue
    accepted.push(zone)
  }

  const rows = []
  for (const zone of keepOneAccepted(accepted)) {
    const signal = bars[zone.end]
    const plan = lockedPlanPrices(bars, zone)
    const rawEntry = plan?.entry ?? zone.entry ?? null
    const rawStop = plan?.stop ?? (Number.isFinite(zone.low) ? zone.low : null)
    let rawTarget = plan?.target ?? null
    if (rawTarget == null && rawEntry != null && rawStop != null && rawEntry > rawStop) {
      rawTarget = rawEntry + (rawEntry - rawStop)
    }
    const prices = sanitizePlanPrices(rawEntry, rawStop, rawTarget, zone.low)

    rows.push({
      symbol: signal.symbol || '',
      zone_start: zone.start,
      zone_end: zone.end,
      pattern: zone.patternType,
      leg_out_mode: zone.legOutMode,
      decided_at: `${signal.date} ${String(signal.clock || '00:00').length === 5 ? `${signal.clock}:00` : signal.clock}`,
      p_accept: zone.probability,
      suggested_entry: prices.entry,
      suggested_stop: prices.stop,
      suggested_target: null,
      hint_target: prices.target,
      uoc_low: zone.low,
      uoc_high: zone.high,
      from: zone.from,
      to: zone.to ?? zone.end,
      markerIndex: zone.markerIndex ?? zone.end,
    })
  }

  rows.sort((left, right) => {
    if (left.decided_at < right.decided_at) return -1
    if (left.decided_at > right.decided_at) return 1
    return left.zone_start - right.zone_start
  })
  return rows
}

/** Stable key for matching a chart zone to a saved dataset.csv row. */
export function reviewKey(symbol, zoneStart, zoneEnd) {
  return `${String(symbol || '').toUpperCase()}|${zoneStart}|${zoneEnd}`
}

export function reviewedMapFromRows(rows) {
  const map = new Map()
  for (const row of rows || []) {
    const key = reviewKey(row.symbol, row.zone_start, row.zone_end)
    map.set(key, row)
  }
  return map
}

export async function loadReviewed(symbol, signal) {
  if (!symbol) return []
  const response = await fetch(`/api/reviewed?symbol=${encodeURIComponent(symbol)}`, { signal })
  const body = await response.json().catch(() => ({ ok: false, error: 'Bad response' }))
  if (!response.ok || !body.ok) {
    throw new Error(body.error || `Could not load reviewed rows (${response.status})`)
  }
  return Array.isArray(body.rows) ? body.rows : []
}

export async function saveManualLabel(payload) {
  const response = await fetch('/api/label', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  const body = await response.json().catch(() => ({ ok: false, error: 'Bad response' }))
  if (!response.ok || !body.ok) {
    throw new Error(body.error || `Save failed (${response.status})`)
  }
  return body.row
}
