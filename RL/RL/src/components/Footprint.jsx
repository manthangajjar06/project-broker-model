import { useLayoutEffect, useRef, useState } from 'react'
import { theme } from '../chart/theme'
import { formatPrice, formatSigned, formatVolume, tone } from '../data/format'

const WIDTH = 220
const MIN_HEIGHT = 160

function clamp(next, stage) {
  const bounds = stage.getBoundingClientRect()
  const h = Math.min(Math.max(MIN_HEIGHT, next.h), Math.max(MIN_HEIGHT, bounds.height - 8))
  const x = Math.min(Math.max(0, next.x), Math.max(0, bounds.width - WIDTH))
  const y = Math.min(Math.max(0, next.y), Math.max(0, bounds.height - h))
  return { x, y, w: WIDTH, h }
}

export default function Footprint({ bars, index }) {
  const panelRef = useRef(null)
  const [box, setBox] = useState(null)
  const safeIndex = bars.length ? (index >= 0 && index < bars.length ? index : bars.length - 1) : -1
  const bar = safeIndex >= 0 ? bars[safeIndex] : null
  const levels = bar?.footprint ?? []

  useLayoutEffect(() => {
    const node = panelRef.current
    if (!node || box) return undefined
    const stage = node.parentElement
    if (!stage) return undefined
    const bounds = stage.getBoundingClientRect()
    setBox({
      x: Math.max(8, bounds.width - WIDTH - 68),
      y: 78,
      w: WIDTH,
      h: Math.min(480, Math.max(MIN_HEIGHT, bounds.height - 140)),
    })
    return undefined
  }, [box, levels.length])

  function startDrag(event, mode) {
    if (event.button !== 0 || !box) return
    const stage = panelRef.current?.parentElement
    if (!stage) return
    event.preventDefault()
    event.stopPropagation()
    const startX = event.clientX
    const startY = event.clientY
    const origin = box

    function move(pointer) {
      const dx = pointer.clientX - startX
      const dy = pointer.clientY - startY
      const next = { ...origin, w: WIDTH }
      if (mode === 'move') {
        next.x += dx
        next.y += dy
      } else if (mode === 's') {
        next.h = origin.h + dy
      } else if (mode === 'n') {
        next.y = origin.y + dy
        next.h = origin.h - dy
      }
      setBox(clamp(next, stage))
    }

    function stop() {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', stop)
    }

    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', stop)
  }

  if (!levels.length) return null
  const peak = levels.reduce((max, level) => Math.max(max, level.buy, level.sell), 0) || 1

  return (
    <aside
      ref={panelRef}
      className="footprint"
      aria-label="Volume footprint"
      style={box ? { left: box.x, top: box.y, width: WIDTH, height: box.h, right: 'auto' } : undefined}
    >
      <header className="footprint-head" onPointerDown={(event) => startDrag(event, 'move')}>
        <span>{bar.date} {bar.clock}</span>
        <span className={tone(bar.delta)}>{formatSigned(bar.delta, 0)}</span>
      </header>
      <div className="footprint-columns">
        <span style={{ color: theme.up }}>Buy</span>
        <span>Price</span>
        <span style={{ color: theme.down }}>Sell</span>
      </div>
      <div className="footprint-rows">
        {levels.map((level) => (
          <div className="footprint-row" key={level.price}>
            <span className="footprint-side buy">
              <i style={{ width: `${(level.buy / peak) * 100}%` }} />
              <b>{formatVolume(level.buy)}</b>
            </span>
            <span className="footprint-price">{formatPrice(level.price)}</span>
            <span className="footprint-side sell">
              <i style={{ width: `${(level.sell / peak) * 100}%` }} />
              <b>{formatVolume(level.sell)}</b>
            </span>
          </div>
        ))}
      </div>
      <i className="footprint-edge n" onPointerDown={(event) => startDrag(event, 'n')} />
      <i className="footprint-edge s" onPointerDown={(event) => startDrag(event, 's')} />
    </aside>
  )
}
