import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { findZones, modelFromText } from '../../RL/src/model/zones.js'
import { parseCsv } from '../../RL/src/data/csv.js'

const here = dirname(fileURLToPath(import.meta.url))
const bars = parseCsv(readFileSync(resolve(here, '../../data/NSE_RELIANCE_2hour.csv'), 'utf8'))
const model = modelFromText(readFileSync(resolve(here, '../../RL/src/model/model.txt'), 'utf8'))
const zones = findZones(bars, model)

process.stdout.write(JSON.stringify({
  bars: bars.length,
  first: { date: bars[0].date, clock: bars[0].clock },
  last: { date: bars[bars.length - 1].date, clock: bars[bars.length - 1].clock },
  zones: zones.map((zone) => ({
    pattern: zone.patternType,
    legOutMode: zone.legOutMode,
    start: zone.start,
    end: zone.end,
    uocLow: zone.low,
    uocHigh: zone.high,
    probability: zone.probability,
    label: zone.label,
    entry: zone.entry,
    warning: zone.warning,
    startDate: bars[zone.start].date,
    startClock: bars[zone.start].clock,
    endDate: bars[zone.end].date,
    endClock: bars[zone.end].clock,
  })),
}))
