/** Company must be older than 3 calendar years before a zone can be labeled. */

export const MIN_COMPANY_YEARS = 3

/**
 * Move an ISO date (YYYY-MM-DD) forward by whole years.
 * Feb 29 becomes Feb 28 when the target year is not a leap year.
 */
export function addCalendarYears(isoDate, years) {
  const [yearText, monthText, dayText] = String(isoDate).slice(0, 10).split('-')
  const year = Number(yearText)
  const month = Number(monthText)
  const day = Number(dayText)
  if (!year || !month || !day) return null

  const targetYear = year + years
  const paddedMonth = String(month).padStart(2, '0')
  let paddedDay = String(day).padStart(2, '0')
  let candidate = `${targetYear}-${paddedMonth}-${paddedDay}`

  // Invalid leap day → roll to Feb 28.
  const probe = new Date(`${candidate}T00:00:00`)
  if (
    Number.isNaN(probe.getTime())
    || probe.getFullYear() !== targetYear
    || probe.getMonth() + 1 !== month
    || probe.getDate() !== day
  ) {
    paddedDay = '28'
    candidate = `${targetYear}-${paddedMonth}-${paddedDay}`
  }
  return candidate
}

/**
 * True when decisionDate is strictly after firstBarDate + years.
 */
export function companyIsOldEnough(firstBarDate, decisionDate, years = MIN_COMPANY_YEARS) {
  if (!firstBarDate || !decisionDate) return false
  const readyAfter = addCalendarYears(firstBarDate, years)
  if (!readyAfter) return false
  return String(decisionDate).slice(0, 10) > readyAfter
}
