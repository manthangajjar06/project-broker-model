import { spawn, spawnSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const here = path.dirname(fileURLToPath(import.meta.url))
const dataDir = path.resolve(here, '../data')
const rlRoot = path.resolve(here, '..')
const datasetPath = path.resolve(here, '../Model/dataset.csv')

/** One long-lived Python process so Save reuses cached bars/model. */
let labelWorker = null
let labelWorkerBuffer = ''
let labelWorkerQueue = Promise.resolve()
let labelWorkerStamp = ''
const labelWorkerWaiters = []

/** Restart the worker when labeling Python files change on disk. */
function labelWorkerCodeStamp() {
  const files = [
    'Model/label_worker.py',
    'Model/manual_label.py',
    'Model/fill.py',
    'Model/load.py',
    'Model/score.py',
    'Model/predict.py',
  ]
  return files
    .map((relative) => {
      const full = path.resolve(rlRoot, relative)
      try {
        return `${relative}:${fs.statSync(full).mtimeMs}`
      } catch {
        return `${relative}:missing`
      }
    })
    .join('|')
}

function parseCsvLine(line) {
  const cells = []
  let current = ''
  let inQuotes = false
  for (let index = 0; index < line.length; index += 1) {
    const ch = line[index]
    if (inQuotes) {
      if (ch === '"' && line[index + 1] === '"') {
        current += '"'
        index += 1
      } else if (ch === '"') {
        inQuotes = false
      } else {
        current += ch
      }
      continue
    }
    if (ch === '"') {
      inQuotes = true
      continue
    }
    if (ch === ',') {
      cells.push(current)
      current = ''
      continue
    }
    current += ch
  }
  cells.push(current)
  return cells
}

/** Slim rows already saved in Model/dataset.csv for one symbol. */
function listReviewedRows(symbol) {
  if (!fs.existsSync(datasetPath)) return []
  const text = fs.readFileSync(datasetPath, 'utf8')
  const lines = text.split(/\r?\n/).filter((line) => line.trim())
  if (lines.length < 2) return []

  const header = parseCsvLine(lines[0])
  const index = Object.fromEntries(header.map((name, position) => [name, position]))
  const needed = ['symbol', 'decided_at', 'zone_start', 'zone_end', 'entry', 'stop', 'target', 'outcome_label', 'y_bounce', 'behavior']
  for (const name of needed) {
    if (index[name] == null) return []
  }

  const key = String(symbol || '').toUpperCase()
  const rows = []
  for (let lineNumber = 1; lineNumber < lines.length; lineNumber += 1) {
    const cells = parseCsvLine(lines[lineNumber])
    const rowSymbol = String(cells[index.symbol] || '').toUpperCase()
    if (rowSymbol !== key) continue
    rows.push({
      symbol: rowSymbol,
      decided_at: cells[index.decided_at] || '',
      zone_start: Number(cells[index.zone_start]),
      zone_end: Number(cells[index.zone_end]),
      entry: Number(cells[index.entry]),
      stop: Number(cells[index.stop]),
      target: Number(cells[index.target]),
      outcome_label: cells[index.outcome_label] || '',
      y_bounce: Number(cells[index.y_bounce]),
      behavior: cells[index.behavior] || '',
    })
  }
  return rows
}

function listSymbols() {
  return fs
    .readdirSync(dataDir)
    .filter((name) => name.toLowerCase().endsWith('.csv'))
    .map((file) => {
      const match = file.match(/^NSE_(.+)_2hour\.csv$/i)
      return {
        file,
        symbol: match ? match[1] : file.replace(/\.csv$/i, ''),
        exchange: 'NSE',
        interval: '2h',
      }
    })
    .sort((a, b) => a.symbol.localeCompare(b.symbol))
}

function sendJson(res, status, body) {
  res.statusCode = status
  res.setHeader('Content-Type', 'application/json; charset=utf-8')
  res.end(JSON.stringify(body))
}

function readRequestBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = []
    req.on('data', (chunk) => chunks.push(chunk))
    req.on('end', () => {
      const raw = Buffer.concat(chunks).toString('utf8')
      if (!raw.trim()) {
        resolve({})
        return
      }
      try {
        resolve(JSON.parse(raw))
      } catch (error) {
        reject(new Error('Request body must be JSON'))
      }
    })
    req.on('error', reject)
  })
}

function pythonCommand() {
  // Prefer the Windows launcher, then plain python.
  return process.platform === 'win32' ? 'python' : 'python3'
}

function workerEnv() {
  return {
    ...process.env,
    PYTHONPATH: rlRoot,
    PYTHONUTF8: '1',
    PYTHONUNBUFFERED: '1',
  }
}

function killLabelWorker() {
  if (!labelWorker) return
  try {
    labelWorker.stdin.end()
  } catch {
    // already closed
  }
  try {
    labelWorker.kill()
  } catch {
    // already dead
  }
  labelWorker = null
  labelWorkerBuffer = ''
  while (labelWorkerWaiters.length) {
    const waiter = labelWorkerWaiters.shift()
    waiter.reject(new Error('Label worker restarted'))
  }
}

function ensureLabelWorker() {
  const stamp = labelWorkerCodeStamp()
  if (labelWorker && !labelWorker.killed && stamp !== labelWorkerStamp) {
    killLabelWorker()
  }
  if (labelWorker && !labelWorker.killed) return labelWorker

  labelWorkerStamp = stamp
  labelWorkerBuffer = ''
  const child = spawn(pythonCommand(), ['-u', '-m', 'Model.label_worker'], {
    cwd: rlRoot,
    env: workerEnv(),
    stdio: ['pipe', 'pipe', 'pipe'],
  })
  labelWorker = child

  child.stdout.setEncoding('utf8')
  child.stdout.on('data', (chunk) => {
    labelWorkerBuffer += chunk
    let newline = labelWorkerBuffer.indexOf('\n')
    while (newline >= 0) {
      const line = labelWorkerBuffer.slice(0, newline).trim()
      labelWorkerBuffer = labelWorkerBuffer.slice(newline + 1)
      const waiter = labelWorkerWaiters.shift()
      if (waiter && line) {
        try {
          waiter.resolve(JSON.parse(line))
        } catch (error) {
          waiter.reject(error instanceof Error ? error : new Error(String(error)))
        }
      }
      newline = labelWorkerBuffer.indexOf('\n')
    }
  })

  child.stderr.setEncoding('utf8')
  child.stderr.on('data', () => {
    // Keep stderr flowing so the pipe never blocks the worker.
  })

  child.on('exit', () => {
    if (labelWorker === child) {
      labelWorker = null
      labelWorkerBuffer = ''
      while (labelWorkerWaiters.length) {
        const waiter = labelWorkerWaiters.shift()
        waiter.reject(new Error('Label worker exited'))
      }
    }
  })

  return child
}

function callLabelWorker(message, timeoutMs = 120_000) {
  const job = labelWorkerQueue.then(
    () =>
      new Promise((resolve, reject) => {
        let settled = false
        const timer = setTimeout(() => {
          if (settled) return
          settled = true
          killLabelWorker()
          reject(new Error(`Label worker timed out after ${timeoutMs}ms`))
        }, timeoutMs)

        const finish = (fn) => (value) => {
          if (settled) return
          settled = true
          clearTimeout(timer)
          fn(value)
        }

        try {
          const child = ensureLabelWorker()
          labelWorkerWaiters.push({
            resolve: finish(resolve),
            reject: finish(reject),
          })
          child.stdin.write(`${JSON.stringify(message)}\n`)
        } catch (error) {
          finish(reject)(error instanceof Error ? error : new Error(String(error)))
        }
      }),
  )

  // Keep the queue alive even when a job fails.
  labelWorkerQueue = job.then(
    () => undefined,
    () => undefined,
  )
  return job
}

/** Cold spawn fallback if the long-lived worker cannot start. */
function runManualLabelSync(args, stdinText) {
  const result = spawnSync(pythonCommand(), ['-m', 'Model.run_manual_label', ...args], {
    cwd: rlRoot,
    encoding: 'utf8',
    input: stdinText,
    env: workerEnv(),
    timeout: 120_000,
    maxBuffer: 16 * 1024 * 1024,
  })

  if (result.error) {
    return { ok: false, error: result.error.message }
  }

  const stdout = (result.stdout || '').trim()
  const stderr = (result.stderr || '').trim()
  if (!stdout) {
    return { ok: false, error: stderr || `Python exited with code ${result.status}` }
  }

  try {
    return JSON.parse(stdout.split('\n').filter(Boolean).at(-1))
  } catch {
    return { ok: false, error: stderr || stdout.slice(0, 500) }
  }
}

async function runManualLabel(args, stdinText) {
  try {
    if (args[0] === 'list') {
      const symbolIndex = args.indexOf('--symbol')
      const symbol = symbolIndex >= 0 ? args[symbolIndex + 1] : ''
      return await callLabelWorker({ cmd: 'list', symbol })
    }
    if (args[0] === 'save') {
      const body = stdinText ? JSON.parse(stdinText) : {}
      return await callLabelWorker({ cmd: 'save', ...body })
    }
  } catch (error) {
    // Fall through to one-shot CLI.
    const message = error instanceof Error ? error.message : String(error)
    if (!message) {
      // ignore
    }
  }
  return runManualLabelSync(args, stdinText)
}

function attachDataApi(middlewares) {
  middlewares.use(async (req, res, next) => {
    const url = (req.url ?? '').split('?')[0]

    // ---- Label APIs (manual Entry / Stop / Target) ----
    if (url === '/api/label-zones' && req.method === 'GET') {
      try {
        const query = new URL(req.url, 'http://localhost').searchParams
        const symbol = (query.get('symbol') || '').trim()
        if (!symbol) {
          sendJson(res, 400, { ok: false, error: 'symbol is required' })
          return
        }
        const payload = await runManualLabel(['list', '--symbol', symbol])
        sendJson(res, payload.ok ? 200 : 500, payload)
      } catch (error) {
        sendJson(res, 500, {
          ok: false,
          error: error instanceof Error ? error.message : 'Could not list zones',
        })
      }
      return
    }

    if (url === '/api/label' && req.method === 'POST') {
      try {
        const body = await readRequestBody(req)
        const payload = await runManualLabel(['save', '--stdin'], JSON.stringify(body))
        sendJson(res, payload.ok ? 200 : 400, payload)
      } catch (error) {
        sendJson(res, 500, {
          ok: false,
          error: error instanceof Error ? error.message : 'Could not save label',
        })
      }
      return
    }

    if (url === '/api/reviewed' && req.method === 'GET') {
      try {
        const query = new URL(req.url, 'http://localhost').searchParams
        const symbol = (query.get('symbol') || '').trim()
        if (!symbol) {
          sendJson(res, 400, { ok: false, error: 'symbol is required' })
          return
        }
        const rows = listReviewedRows(symbol)
        sendJson(res, 200, { ok: true, symbol: symbol.toUpperCase(), count: rows.length, rows })
      } catch (error) {
        sendJson(res, 500, {
          ok: false,
          error: error instanceof Error ? error.message : 'Could not read reviewed rows',
        })
      }
      return
    }

    // ---- Existing OHLCV APIs ----
    if (url !== '/api/symbols' && !url.startsWith('/api/csv/')) {
      next()
      return
    }

    if (!fs.existsSync(dataDir)) {
      sendJson(res, 500, { error: 'Data folder not found' })
      return
    }

    if (url === '/api/symbols') {
      try {
        sendJson(res, 200, listSymbols())
      } catch (error) {
        sendJson(res, 500, { error: error instanceof Error ? error.message : 'Could not list symbols' })
      }
      return
    }

    let requested = url.slice('/api/csv/'.length)
    try {
      requested = decodeURIComponent(requested)
    } catch {
      sendJson(res, 400, { error: 'Bad file name' })
      return
    }

    const name = path.basename(requested)
    if (!name || name !== requested || !name.toLowerCase().endsWith('.csv')) {
      sendJson(res, 400, { error: 'Bad file name' })
      return
    }

    const full = path.resolve(dataDir, name)
    const relative = path.relative(dataDir, full)
    if (relative.startsWith('..') || path.isAbsolute(relative) || !fs.existsSync(full)) {
      sendJson(res, 404, { error: 'File not found' })
      return
    }

    res.statusCode = 200
    res.setHeader('Content-Type', 'text/csv; charset=utf-8')
    fs.createReadStream(full).pipe(res)
  })
}

function ohlcvDataPlugin() {
  return {
    name: 'ohlcv-data',
    configureServer(server) {
      attachDataApi(server.middlewares)
      // Warm the worker so the first Save is not a cold Python start.
      ensureLabelWorker()
      server.httpServer?.once('close', () => {
        killLabelWorker()
      })
    },
    configurePreviewServer(server) {
      attachDataApi(server.middlewares)
      ensureLabelWorker()
      server.httpServer?.once('close', () => {
        killLabelWorker()
      })
    },
  }
}

export default defineConfig({
  plugins: [react(), ohlcvDataPlugin()],
})
