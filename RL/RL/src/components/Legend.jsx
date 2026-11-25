import { theme } from '../chart/theme'
import {
  formatPercent,
  formatPrice,
  formatSigned,
  formatVolume,
  tone,
} from '../data/format'

function Field({ label, value, color, toneName }) {
  return (
    <span className="legend-item">
      {color && <i className="swatch" style={{ background: color }} />}
      <span className="legend-label" style={color ? { color } : undefined}>{label}</span>
      <span className={toneName ? `legend-value ${toneName}` : 'legend-value'}>{value}</span>
    </span>
  )
}

/**
 * @param {{ bars: any[], index: number, compact?: boolean }} props
 * compact = label mode: OHLC + EMAs only, so the chart stays readable.
 */
export default function Legend({ bars, index, compact = false }) {
  if (!bars.length) return null
  const safeIndex = index >= 0 && index < bars.length ? index : bars.length - 1
  const bar = bars[safeIndex]
  const previous = safeIndex > 0 ? bars[safeIndex - 1] : null
  const change = previous ? bar.close - previous.close : 0
  const percent = previous && previous.close ? (change / previous.close) * 100 : 0
  const direction = bar.close >= bar.open ? 'up' : 'down'

  return (
    <div className={`legend${compact ? ' legend-compact' : ''}`}>
      <div className="legend-row">
        <Field label="O" value={formatPrice(bar.open)} />
        <Field label="H" value={formatPrice(bar.high)} />
        <Field label="L" value={formatPrice(bar.low)} />
        <Field label="C" value={formatPrice(bar.close)} toneName={direction} />
        <span className={`legend-change ${tone(change)}`}>
          {formatSigned(change)} ({formatSigned(percent)}%)
        </span>
        <Field label="EMA 20" value={formatPrice(bar.ema20)} color={theme.ema20} />
        <Field label="EMA 50" value={formatPrice(bar.ema50)} color={theme.ema50} />
      </div>
      {!compact && (
        <>
          <div className="legend-row">
            <Field label="Volume" value={formatVolume(bar.volume)} color={direction === 'up' ? theme.up : theme.down} />
            <Field label="Avg vol 14D" value={formatVolume(bar.avgVolume)} color={theme.avgVolume} />
            <Field label="Upper wick" value={formatPercent(bar.upperWick)} />
            <Field label="Lower wick" value={formatPercent(bar.lowerWick)} />
            <Field label="Body" value={formatPercent(bar.body)} />
          </div>
          <div className="legend-row">
            <Field label="TR" value={formatPrice(bar.tr)} color={theme.muted} />
            <Field label="ATR 14" value={formatPrice(bar.atr)} color={theme.atr} />
            <Field label="DATR 14" value={formatPrice(bar.datr)} color={theme.datr} />
            <Field label="Buy" value={formatVolume(bar.buyVolume)} color={theme.up} />
            <Field label="Sell" value={formatVolume(bar.sellVolume)} color={theme.down} />
            <Field label="Delta" value={formatSigned(bar.delta, 0)} toneName={tone(bar.delta)} />
          </div>
        </>
      )}
    </div>
  )
}
