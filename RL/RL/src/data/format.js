const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export function displaySymbol(symbol) {
  if (!symbol) return ''
  return symbol.startsWith('NSE:') ? symbol.slice(4) : symbol
}

export function intervalLabel(interval) {
  if (!interval || interval === '2hour' || interval === '2h') return '2h'
  return interval
}

export function formatPrice(value) {
  if (value == null || !Number.isFinite(value)) return '—'
  return value.toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

export function formatSigned(value, digits = 2) {
  if (value == null || !Number.isFinite(value)) return '—'
  const text = Math.abs(value).toLocaleString('en-IN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
  if (value > 0) return `+${text}`
  if (value < 0) return `-${text}`
  return text
}

export function formatVolume(value) {
  if (value == null || !Number.isFinite(value)) return '—'
  const abs = Math.abs(value)
  const sign = value < 0 ? '-' : ''
  if (abs >= 1e9) return `${sign}${(abs / 1e9).toFixed(2)}B`
  if (abs >= 1e6) return `${sign}${(abs / 1e6).toFixed(2)}M`
  if (abs >= 1e3) return `${sign}${(abs / 1e3).toFixed(2)}K`
  return `${sign}${abs.toFixed(0)}`
}

export function formatPercent(value) {
  if (value == null || !Number.isFinite(value)) return '—'
  return `${value.toFixed(2)}%`
}

export function formatCount(value) {
  return value.toLocaleString('en-IN')
}

export function formatBarStamp(date, clock) {
  if (!date) return '—'
  const [year, month, day] = date.split('-')
  const monthName = MONTHS[Number(month) - 1] ?? month
  const stamp = `${Number(day)} ${monthName} '${String(year).slice(2)}`
  return clock ? `${stamp}  ${clock}` : stamp
}

export function formatMonthYear(date) {
  if (!date) return ''
  const [year, month] = date.split('-')
  return `${MONTHS[Number(month) - 1] ?? month} ${year}`
}

export function tone(value) {
  if (value == null || !Number.isFinite(value) || value === 0) return 'flat'
  return value > 0 ? 'up' : 'down'
}
