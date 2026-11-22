import { useEffect, useRef, useState } from 'react'

export default function SymbolSearch({ symbols, current, onSelect }) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const wrapRef = useRef(null)
  const inputRef = useRef(null)
  const listRef = useRef(null)

  const needle = query.trim().toLowerCase()
  const filtered = needle
    ? symbols.filter((item) => item.symbol.toLowerCase().includes(needle))
    : symbols

  useEffect(() => {
    if (!open) return undefined
    const frame = requestAnimationFrame(() => inputRef.current?.focus())
    function onPointerDown(event) {
      if (!wrapRef.current?.contains(event.target)) setOpen(false)
    }
    function onKey(event) {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKey)
    return () => {
      cancelAnimationFrame(frame)
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    listRef.current?.children[active]?.scrollIntoView({ block: 'nearest' })
  }, [active, open, filtered.length])

  function choose(item) {
    onSelect(item)
    setOpen(false)
  }

  function onInputKey(event) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setActive((index) => Math.min(index + 1, Math.max(filtered.length - 1, 0)))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActive((index) => Math.max(index - 1, 0))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      const item = filtered[active]
      if (item) choose(item)
    }
  }

  return (
    <div className="symbol-wrap" ref={wrapRef}>
      <button
        type="button"
        className="symbol-button"
        onClick={() => {
          if (!open) {
            setQuery('')
            setActive(0)
          }
          setOpen((value) => !value)
        }}
        aria-expanded={open}
        aria-haspopup="listbox"
      >
        <span className="exchange">NSE</span>
        <span className="symbol-name">{current?.symbol ?? 'Symbol'}</span>
        <svg className="caret" viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
          <path d="M2.5 4.5 6 8l3.5-3.5" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
        </svg>
      </button>
      {open && (
        <div className="symbol-menu">
          <input
            ref={inputRef}
            className="symbol-search"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value)
              setActive(0)
            }}
            onKeyDown={onInputKey}
            placeholder="Search symbol"
            aria-label="Search symbol"
            spellCheck="false"
          />
          <div className="symbol-meta">{filtered.length} symbols</div>
          <ul className="symbol-list" ref={listRef} role="listbox">
            {filtered.length === 0 && <li className="symbol-empty">No match</li>}
            {filtered.map((item, index) => (
              <li key={item.file}>
                <button
                  type="button"
                  role="option"
                  aria-selected={item.symbol === current?.symbol}
                  className={`symbol-option${index === active ? ' active' : ''}${item.symbol === current?.symbol ? ' current' : ''}`}
                  onMouseEnter={() => setActive(index)}
                  onClick={() => choose(item)}
                >
                  <span>{item.symbol}</span>
                  <span className="symbol-exchange">{item.exchange}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
