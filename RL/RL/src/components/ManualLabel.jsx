import { useEffect, useState } from 'react'
import { reviewKey, saveManualLabel } from '../data/labelZones'

/**
 * Walk accepted zones (company age > 3 years).
 * Entry / SL / Target can be typed here or dragged on the chart handles.
 * Skip marks the zone as bad_entry without using the path as a bounce sample.
 */
export default function ManualLabel({
  zones,
  index,
  onIndexChange,
  entry,
  stop,
  target,
  onPricesChange,
  disabled,
  symbol,
  reviewedMap,
  onSaved,
}) {
  const [status, setStatus] = useState('')
  const [saving, setSaving] = useState(false)
  const zone = zones[index] ?? null

  const reviewed = zone
    ? reviewedMap?.get(reviewKey(symbol, zone.zone_start, zone.zone_end))
    : null

  useEffect(() => {
    setStatus('')
  }, [index, symbol])

  if (!zones.length) {
    return (
      <div className="manual-label manual-label-empty">
        No accepted zones after the 3-year company gate for this symbol
      </div>
    )
  }

  if (!zone) {
    return <div className="manual-label manual-label-empty">No zone selected</div>
  }

  async function persist(forceLabel) {
    const entryNumber = Number(entry)
    const stopNumber = Number(stop)
    const targetNumber = Number(target)

    if (![entryNumber, stopNumber, targetNumber].every(Number.isFinite)) {
      setStatus('Enter numeric Entry, Stop, and Target first.')
      return
    }
    if (!(stopNumber < entryNumber && entryNumber < targetNumber)) {
      setStatus('Require stop < entry < target.')
      return
    }

    setSaving(true)
    setStatus(forceLabel === 'bad_entry' ? 'Skipping…' : 'Saving…')
    try {
      const row = await saveManualLabel({
        symbol,
        zone_start: zone.zone_start,
        zone_end: zone.zone_end,
        entry: entryNumber,
        stop: stopNumber,
        target: targetNumber,
        force_label: forceLabel || undefined,
      })
      const verb = forceLabel === 'bad_entry'
        ? 'Skipped (bad entry)'
        : `Saved ${row.outcome_label}`
      setStatus(
        `${verb}`
        + (row.updated ? ' (updated)' : '')
        + (forceLabel ? '' : ` · y_bounce=${row.y_bounce}`),
      )
      if (typeof onSaved === 'function') {
        onSaved({
          symbol: row.symbol || symbol,
          decided_at: row.decided_at,
          zone_start: zone.zone_start,
          zone_end: zone.zone_end,
          entry: row.entry,
          stop: row.stop,
          target: row.target,
          outcome_label: row.outcome_label,
          y_bounce: row.y_bounce,
          behavior: row.behavior,
        })
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  function setField(field, value) {
    onPricesChange({
      entry: field === 'entry' ? value : entry,
      stop: field === 'stop' ? value : stop,
      target: field === 'target' ? value : target,
    })
  }

  const modeLabel = String(zone.leg_out_mode || '').includes('SUPER') ? 'SUPER' : 'SINGLE'
  const defaultHint = reviewed
    ? `Reviewed already · ${reviewed.outcome_label || 'saved'}`
    : 'Drag blue handles on the right of the box'

  return (
    <div className="manual-label">
      <button
        type="button"
        className="outcome-nav"
        disabled={disabled || saving || index <= 0}
        onClick={() => onIndexChange(index - 1)}
        title="Previous accepted zone"
      >
        ‹
      </button>

      <div className="manual-zone">
        <span className="outcome-count">{index + 1} / {zones.length}</span>
        <span className="outcome-date">{zone.decided_at}</span>
        <span className="outcome-tag flat">{zone.pattern}</span>
        <span className="outcome-tag flat">{modeLabel}</span>
        <span className="outcome-tag flat">p {Number(zone.p_accept).toFixed(2)}</span>
        {reviewed ? (
          <span
            className={`outcome-tag ${reviewed.outcome_label === 'bad_entry' ? 'skipped' : 'reviewed'}`}
            title={reviewed.outcome_label || 'saved'}
          >
            {reviewed.outcome_label === 'bad_entry'
              ? 'Skipped · bad entry'
              : `Reviewed already · ${reviewed.outcome_label || 'saved'}`}
          </span>
        ) : (
          <span className="outcome-tag flat">Not reviewed</span>
        )}
      </div>

      <div className="manual-fields">
        <label className="manual-field">
          <span>Entry</span>
          <input
            type="number"
            step="any"
            value={entry}
            disabled={disabled || saving}
            onChange={(event) => setField('entry', event.target.value)}
          />
        </label>
        <label className="manual-field">
          <span>SL</span>
          <input
            type="number"
            step="any"
            value={stop}
            disabled={disabled || saving}
            onChange={(event) => setField('stop', event.target.value)}
          />
        </label>
        <label className="manual-field">
          <span>Target</span>
          <input
            type="number"
            step="any"
            value={target}
            disabled={disabled || saving}
            onChange={(event) => setField('target', event.target.value)}
          />
        </label>
        <button
          type="button"
          className="manual-save"
          disabled={disabled || saving}
          onClick={() => persist(null)}
        >
          {reviewed && reviewed.outcome_label !== 'bad_entry' ? 'Update' : 'Save'}
        </button>
        <button
          type="button"
          className="manual-skip"
          disabled={disabled || saving}
          onClick={() => persist('bad_entry')}
          title="Mark this zone as a bad entry and skip it"
        >
          Skip
        </button>
      </div>

      <div className="manual-status" title={status || defaultHint}>
        {status || defaultHint}
      </div>

      <button
        type="button"
        className="outcome-nav"
        disabled={disabled || saving || index >= zones.length - 1}
        onClick={() => onIndexChange(index + 1)}
        title="Next accepted zone"
      >
        ›
      </button>
    </div>
  )
}
