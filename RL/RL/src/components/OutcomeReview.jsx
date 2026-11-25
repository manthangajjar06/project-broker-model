import { formatPrice } from '../data/format'

export default function OutcomeReview({ rows, index, onIndexChange, disabled }) {
  if (!rows.length) {
    return <span className="range">No outcome rows for this symbol</span>
  }

  const row = rows[index] ?? rows[0]
  const bounce = row.y_bounce === 1
  const label = bounce ? 'bounce' : 'no bounce'

  return (
    <div className="outcome-review">
      <button
        type="button"
        className="outcome-nav"
        disabled={disabled || index <= 0}
        onClick={() => onIndexChange(index - 1)}
        title="Previous outcome"
      >
        ‹
      </button>
      <div className="outcome-meta">
        <span className="outcome-count">
          {index + 1} / {rows.length}
        </span>
        <span className="outcome-date">{row.decided_at}</span>
        <span className={`outcome-tag ${bounce ? 'up' : 'down'}`}>{label}</span>
        <span className="outcome-tag flat">{row.behavior}</span>
        <span className="outcome-tag flat">{row.trade_result}</span>
        <span className="outcome-tag flat">{row.split}</span>
        <span className="outcome-levels">
          E {formatPrice(row.entry)} · S {formatPrice(row.stop)} · T {formatPrice(row.target)}
        </span>
      </div>
      <button
        type="button"
        className="outcome-nav"
        disabled={disabled || index >= rows.length - 1}
        onClick={() => onIndexChange(index + 1)}
        title="Next outcome"
      >
        ›
      </button>
    </div>
  )
}
