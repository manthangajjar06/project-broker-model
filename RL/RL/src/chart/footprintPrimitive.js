import { LEFT_PAD } from './seriesData'
import { theme } from './theme'

const MIN_SPACING = 18
const MAX_VISIBLE = 48

class FootprintRenderer {
  constructor(source) {
    this.source = source
  }

  draw(target) {
    const { chart, series, bars } = this.source
    if (!chart || !series || !bars.length) return
    const range = chart.timeScale().getVisibleLogicalRange()
    const spacing = chart.timeScale().options().barSpacing
    if (!range || spacing < MIN_SPACING) return

    const from = Math.max(0, Math.floor(range.from - LEFT_PAD))
    const to = Math.min(bars.length - 1, Math.ceil(range.to - LEFT_PAD))
    if (to - from > MAX_VISIBLE) return

    target.useBitmapCoordinateSpace((scope) => {
      const context = scope.context
      const horizontal = scope.horizontalPixelRatio
      const vertical = scope.verticalPixelRatio
      const half = Math.max(4, (spacing * 0.42) * horizontal)

      for (let index = from; index <= to; index += 1) {
        const bar = bars[index]
        const levels = bar?.footprint
        if (!levels?.length) continue
        const xCss = chart.timeScale().logicalToCoordinate(LEFT_PAD + index)
        if (xCss == null) continue
        const x = xCss * horizontal
        const peak = levels.reduce((max, level) => Math.max(max, level.buy, level.sell), 0)
        if (!peak) continue

        for (const level of levels) {
          const yTop = series.priceToCoordinate(level.price + 0.125)
          const yBottom = series.priceToCoordinate(level.price - 0.125)
          if (yTop == null || yBottom == null) continue
          const top = Math.min(yTop, yBottom) * vertical
          const height = Math.max(1, Math.abs(yBottom - yTop) * vertical - 1)
          if (height < 1.5) continue
          const buyWidth = (level.buy / peak) * half
          const sellWidth = (level.sell / peak) * half
          context.fillStyle = theme.volumeUp
          context.fillRect(x - buyWidth, top, buyWidth, height)
          context.fillStyle = theme.volumeDown
          context.fillRect(x, top, sellWidth, height)
        }
      }
    })
  }
}

class FootprintPaneView {
  constructor(source) {
    this.source = source
    this.paneRenderer = new FootprintRenderer(source)
  }

  zOrder() {
    return 'bottom'
  }

  renderer() {
    return this.paneRenderer
  }
}

export class FootprintPrimitive {
  constructor() {
    this.bars = []
    this.chart = null
    this.series = null
    this.requestUpdate = () => {}
    this.view = new FootprintPaneView(this)
  }

  attached({ chart, series, requestUpdate }) {
    this.chart = chart
    this.series = series
    this.requestUpdate = requestUpdate
  }

  detached() {
    this.chart = null
    this.series = null
  }

  setBars(bars) {
    this.bars = bars
    this.requestUpdate()
  }

  updateAllViews() {}

  paneViews() {
    return [this.view]
  }
}
