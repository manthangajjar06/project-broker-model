import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const dataDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../data')

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

function attachDataApi(middlewares) {
  middlewares.use((req, res, next) => {
    const url = (req.url ?? '').split('?')[0]
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
    },
    configurePreviewServer(server) {
      attachDataApi(server.middlewares)
    },
  }
}

export default defineConfig({
  plugins: [react(), ohlcvDataPlugin()],
})
