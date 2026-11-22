import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseCsv } from '../../RL/src/data/csv.js'
import { planFor } from '../../RL/src/model/plan.js'
import { findZones, modelFromText } from '../../RL/src/model/zones.js'

const here = dirname(fileURLToPath(import.meta.url))
const bars = parseCsv(readFileSync(resolve(here, '../../data/NSE_RELIANCE_2hour.csv'), 'utf8'))
const model = modelFromText(readFileSync(resolve(here, '../../RL/src/model/model.txt'), 'utf8'))
const plans = []
for (const zone of findZones(bars, model)) {
  const plan = planFor(bars, zone)
  plans.push(plan
    ? { start: zone.start, end: zone.end, entry: plan.entry, stop: plan.stop, target: plan.target }
    : { start: zone.start, end: zone.end, entry: null, stop: null, target: null })
}
process.stdout.write(JSON.stringify(plans))
