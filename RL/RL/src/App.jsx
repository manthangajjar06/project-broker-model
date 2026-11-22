import { useEffect, useState } from 'react'
import ChartStage from './chart/ChartStage'
import Footprint from './components/Footprint'
import Legend from './components/Legend'
import SymbolSearch from './components/SymbolSearch'
import { parseCsv } from './data/csv'
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

  function chooseSymbol(item) {
    if (!item || item.file === selected?.file) return
    setError('')
    setSelected(item)
  }

  return (
    <div className="app">
      <header className="toolbar">
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
        {loading && (
          <span className="range">
            {bars.length === 0 ? 'Loading chart…' : `Loading ${selected?.symbol ?? ''}…`}
          </span>
        )}
      </header>
      {error && <div className="banner" role="alert">{error}</div>}
      <main className="stage">
        <ChartStage bars={bars} symbol={loadedName} onIndexChange={setActiveIndex} />
        <Legend bars={bars} index={activeIndex} />
        <Footprint bars={bars} index={activeIndex} />
        {!loading && !bars.length && !error && (
          <div className="empty">Choose a symbol to open its 2-hour chart.</div>
        )}
      </main>
    </div>
  )
}
