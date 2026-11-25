import { useEffect, useMemo, useState } from 'react'
import modelText from './model/model.txt?raw'
import ChartStage from './chart/ChartStage'
import Footprint from './components/Footprint'
import Legend from './components/Legend'
import ManualLabel from './components/ManualLabel'
import OutcomeReview from './components/OutcomeReview'
import SymbolSearch from './components/SymbolSearch'
import { parseCsv } from './data/csv'
import {
  buildLabelableZones,
  loadReviewed,
  reviewKey,
  reviewedMapFromRows,
} from './data/labelZones'
import { loadOutcomes, outcomesForSymbol } from './data/outcomes'
import { displaySymbol, formatPrice, formatSigned, intervalLabel, tone } from './data/format'
import './styles/app.css'

export default function App() {
  const [symbols, setSymbols] = useState([])
  const [selected, setSelected] = useState(null)
  const [bars, setBars] = useState([])
  const [activeIndex, setActiveIndex] = useState(-1)
  const [catalogState, setCatalogState] = useState('loading')
  const [loadedFile, setLoadedFile] = useState('')
  const [error, setError] = useState('')
  const [allOutcomes, setAllOutcomes] = useState([])
  const [outcomeIndex, setOutcomeIndex] = useState(0)
  const [reviewMode, setReviewMode] = useState(false)
  const [labelMode, setLabelMode] = useState(true)
  const [labelIndex, setLabelIndex] = useState(0)
  const [prices, setPrices] = useState({ entry: '', stop: '', target: '' })
  const [reviewedRows, setReviewedRows] = useState([])

  useEffect(() => {
    const controller = new AbortController()
    fetch('/api/symbols', { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error('Could not read the symbol list')
        return response.json()
      })
      .then((list) => {
        setSymbols(list)
        setCatalogState('ready')
        setSelected(list.find((item) => item.symbol === 'RELIANCE') ?? list[0] ?? null)
        if (!list.length) setError('No CSV files found in the data folder.')
      })
      .catch((reason) => {
        if (reason?.name === 'AbortError') return
        setCatalogState('ready')
        setError(reason instanceof Error ? reason.message : 'Could not read the symbol list')
      })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    loadOutcomes(controller.signal)
      .then((rows) => setAllOutcomes(rows))
      .catch((reason) => {
        if (reason?.name === 'AbortError') return
        console.warn(reason)
      })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    if (!selected) return undefined
    const controller = new AbortController()
    const file = selected.file
    let active = true
    fetch(`/api/csv/${encodeURIComponent(file)}`, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`Could not load ${selected.symbol}`)
        return response.text()
      })
      .then((text) => {
        if (!active) return
        const parsed = parseCsv(text)
        if (!parsed.length) throw new Error(`${selected.symbol} has no candles`)
        setBars(parsed)
        setActiveIndex(parsed.length - 1)
        setLoadedFile(file)
        setError('')
      })
      .catch((reason) => {
        if (!active || reason?.name === 'AbortError') return
        setError(reason instanceof Error ? reason.message : `Could not load ${selected.symbol}`)
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [selected])

  const symbolOutcomes = useMemo(
    () => outcomesForSymbol(allOutcomes, selected?.symbol),
    [allOutcomes, selected],
  )

  const labelZones = useMemo(
    () => (labelMode ? buildLabelableZones(bars, modelText) : []),
    [bars, labelMode],
  )

  useEffect(() => {
    setOutcomeIndex(0)
  }, [selected?.symbol, symbolOutcomes.length])

  useEffect(() => {
    setLabelIndex(0)
  }, [selected?.symbol, labelZones.length])

  useEffect(() => {
    if (!selected?.symbol || !labelMode) {
      setReviewedRows([])
      return undefined
    }
    const controller = new AbortController()
    loadReviewed(selected.symbol, controller.signal)
      .then((rows) => setReviewedRows(rows))
      .catch((reason) => {
        if (reason?.name === 'AbortError') return
        console.warn(reason)
        setReviewedRows([])
      })
    return () => controller.abort()
  }, [selected?.symbol, labelMode])

  const reviewedMap = useMemo(() => reviewedMapFromRows(reviewedRows), [reviewedRows])

  useEffect(() => {
    const zone = labelZones[labelIndex]
    if (!zone) {
      setPrices({ entry: '', stop: '', target: '' })
      return
    }

    const saved = reviewedMap.get(
      reviewKey(selected?.symbol, zone.zone_start, zone.zone_end),
    )

    // Prefer previously saved prices when this zone was already reviewed.
    if (saved && [saved.entry, saved.stop, saved.target].every(Number.isFinite)) {
      let entry = Number(saved.entry)
      let stop = Number(saved.stop)
      let target = Number(saved.target)
      if (!(stop < entry)) {
        const gap = Math.max(Math.abs(stop) * 1e-4, 0.01)
        entry = stop + gap
      }
      if (!(target > entry)) {
        target = entry + Math.max(entry - stop, 0.01)
      }
      setPrices({
        entry: entry.toFixed(2),
        stop: stop.toFixed(2),
        target: target.toFixed(2),
      })
      return
    }

    let entry = zone.suggested_entry
    let stop = zone.suggested_stop
    let target = zone.hint_target
    // Keep a drawable long box even when §15 raw entry sits at/below stop.
    if (Number.isFinite(entry) && Number.isFinite(stop) && !(stop < entry)) {
      const gap = Math.max(Math.abs(stop) * 1e-4, 0.01)
      entry = stop + gap
    }
    if (Number.isFinite(entry) && Number.isFinite(stop) && !(Number.isFinite(target) && target > entry)) {
      target = entry + Math.max(entry - stop, 0.01)
    }

    setPrices({
      entry: entry != null && Number.isFinite(Number(entry)) ? Number(entry).toFixed(2) : '',
      stop: stop != null && Number.isFinite(Number(stop)) ? Number(stop).toFixed(2) : '',
      target: target != null && Number.isFinite(Number(target)) ? Number(target).toFixed(2) : '',
    })
  }, [labelZones, labelIndex, reviewedMap, selected?.symbol])

  useEffect(() => {
    const name = selected?.symbol ?? 'Chart'
    document.title = `${name} · 2h`
  }, [selected])

  const last = bars.length ? bars[bars.length - 1] : null
  const previous = bars.length > 1 ? bars[bars.length - 2] : null
  const change = last && previous ? last.close - previous.close : 0
  const changePercent = previous?.close ? (change / previous.close) * 100 : 0
  const loadedName = displaySymbol(last?.symbol) || selected?.symbol || ''
  const loading = catalogState === 'loading' || Boolean(selected && loadedFile !== selected.file && !error)
  const reviewRow = reviewMode && !labelMode && symbolOutcomes.length
    ? symbolOutcomes[outcomeIndex]
    : null
  const labelZone = labelMode && labelZones.length ? labelZones[labelIndex] : null
  const labelLevel = (() => {
    if (!labelZone) return null
    const lastBar = Math.max(bars.length - 1, 0)
    const zoneStart = Number.isFinite(labelZone.zone_start)
      ? labelZone.zone_start
      : (Number.isFinite(labelZone.from) ? labelZone.from : 0)
    const decision = Number.isFinite(labelZone.markerIndex)
      ? labelZone.markerIndex
      : (Number.isFinite(labelZone.zone_end) ? labelZone.zone_end : zoneStart)
    // Path window after the decision (same +40 as before).
    const pathEnd = Math.min(decision + 40, lastBar)
    // First zone retest, if known — keep the box covering that too.
    const touchEnd = Number.isFinite(labelZone.to) ? Math.min(labelZone.to, lastBar) : pathEnd
    // Extra bars before leg-in so the impulse into the zone stays visible.
    const LEG_IN_LOOKBACK = 18
    return {
      // Behind the zone (leg-in + lookback) AND forward into the path.
      from: Math.max(0, zoneStart - LEG_IN_LOOKBACK),
      to: Math.max(pathEnd, touchEnd),
      // Camera / crosshair stay on the decision candle, not the left edge.
      focus: decision,
      // UOC = base candle (leg-in + 1). Marker sits under its low.
      uocIndex: zoneStart + 1,
      uocLow: Number.isFinite(labelZone.uoc_low) ? labelZone.uoc_low : null,
      zoneKey: `${labelZone.zone_start}-${labelZone.zone_end}-${labelZone.decided_at}`,
      entry: Number(prices.entry),
      stop: Number(prices.stop),
      target: Number(prices.target),
    }
  })()

  function chooseSymbol(item) {
    if (!item || item.file === selected?.file) return
    setError('')
    setSelected(item)
  }

  return (
    <div className="app">
      <header className="chrome">
        <div className="toolbar">
          <SymbolSearch symbols={symbols} current={selected} onSelect={chooseSymbol} />
          <span className="interval">{intervalLabel(last?.interval || selected?.interval)}</span>
          {last && (
            <div className={`quote ${tone(change)}`}>
              <span className="quote-price">{formatPrice(last.close)}</span>
              <span className="quote-change">
                {formatSigned(change)} ({formatSigned(changePercent)}%)
              </span>
            </div>
          )}

          <div className="toolbar-fill" />

          <label className="outcome-toggle">
            <input
              type="checkbox"
              checked={labelMode}
              onChange={(event) => {
                const on = event.target.checked
                setLabelMode(on)
                if (on) setReviewMode(false)
              }}
            />
            Label zones
          </label>

          <label className="outcome-toggle">
            <input
              type="checkbox"
              checked={reviewMode}
              onChange={(event) => {
                const on = event.target.checked
                setReviewMode(on)
                if (on) setLabelMode(false)
              }}
            />
            Outcome review
          </label>

          {loading && (
            <span className="range">
              {bars.length === 0 ? 'Loading…' : `Loading ${selected?.symbol ?? ''}…`}
            </span>
          )}
        </div>

        {labelMode && (
          <div className="label-bar">
            <ManualLabel
              zones={labelZones}
              index={labelIndex}
              onIndexChange={setLabelIndex}
              entry={prices.entry}
              stop={prices.stop}
              target={prices.target}
              onPricesChange={setPrices}
              disabled={loading}
              symbol={selected?.symbol || ''}
              reviewedMap={reviewedMap}
              onSaved={(row) => {
                setReviewedRows((previous) => {
                  const key = reviewKey(row.symbol, row.zone_start, row.zone_end)
                  const next = previous.filter(
                    (item) => reviewKey(item.symbol, item.zone_start, item.zone_end) !== key,
                  )
                  next.push(row)
                  return next
                })
              }}
            />
          </div>
        )}

        {reviewMode && !labelMode && (
          <div className="label-bar">
            <OutcomeReview
              rows={symbolOutcomes}
              index={outcomeIndex}
              onIndexChange={setOutcomeIndex}
              disabled={loading}
            />
          </div>
        )}
      </header>

      {error && <div className="banner" role="alert">{error}</div>}

      <main className="stage">
        <ChartStage
          bars={bars}
          symbol={loadedName}
          reviewRow={reviewRow}
          labelLevel={labelLevel}
          onIndexChange={setActiveIndex}
          onLabelPricesChange={(next) => {
            setPrices({
              entry: next.entry,
              stop: next.stop,
              target: next.target,
            })
          }}
        />
        <Legend bars={bars} index={activeIndex} compact={labelMode} />
        {!labelMode && <Footprint bars={bars} index={activeIndex} />}
        {!loading && !bars.length && !error && (
          <div className="empty">Choose a symbol to open its 2-hour chart.</div>
        )}
      </main>
    </div>
  )
}
