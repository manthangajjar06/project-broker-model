import {
  CandlestickSeries,
  ColorType,
  createChart,
  createTextWatermark,
  CrosshairMode,
  LineSeries,
  LineStyle,
} from 'lightweight-charts'
import { priceFormat, theme } from './theme'

/** Default mouse / touch behaviour — chart must stay freely pannable. */
export const CHART_INTERACTION = {
  handleScroll: {
    mouseWheel: true,
    pressedMouseMove: true,
    horzTouchDrag: true,
    vertTouchDrag: true,
  },
  handleScale: {
    axisPressedMouseMove: {
      time: true,
      price: true,
    },
    axisDoubleClickReset: {
      time: true,
      price: false,
    },
    mouseWheel: true,
    pinch: true,
  },
}

/** Restore pan/zoom handles only. Never touch autoScale / visible range. */
export function restoreChartInteraction(chart) {
  if (!chart) return
  chart.applyOptions(CHART_INTERACTION)
}

export function createPriceChart(container) {
  const chart = createChart(container, {
    autoSize: true,
    layout: {
      background: { type: ColorType.Solid, color: theme.background },
      textColor: theme.text,
      fontFamily: theme.font,
      fontSize: 12,
      attributionLogo: false,
      panes: {
        enableResize: true,
        separatorColor: theme.border,
        separatorHoverColor: 'rgba(41, 98, 255, 0.2)',
      },
    },
    grid: {
      vertLines: { color: theme.grid, visible: true },
      horzLines: { color: theme.grid, visible: true },
    },
    crosshair: {
      mode: CrosshairMode.Normal,
      vertLine: {
        color: theme.crosshair,
        width: 1,
        style: LineStyle.Dashed,
        labelBackgroundColor: theme.text,
      },
      horzLine: {
        color: theme.crosshair,
        width: 1,
        style: LineStyle.Dashed,
        labelBackgroundColor: theme.text,
      },
    },
    rightPriceScale: {
      borderColor: theme.border,
      autoScale: true,
      scaleMargins: { top: 0.08, bottom: 0.08 },
    },
    leftPriceScale: { visible: false },
    timeScale: {
      borderColor: theme.border,
      timeVisible: true,
      secondsVisible: false,
      rightOffset: 4,
      barSpacing: 8,
      minBarSpacing: 0.5,
      fixLeftEdge: false,
      fixRightEdge: false,
    },
    localization: {
      locale: 'en-GB',
      dateFormat: "dd MMM 'yy",
    },
    ...CHART_INTERACTION,
  })

  // EMAs first so candles paint on top of them (lines stay visible under bodies/wicks).
  const ema20 = chart.addSeries(LineSeries, {
    color: theme.ema20,
    lineWidth: 2,
    priceFormat,
    priceLineVisible: false,
    lastValueVisible: false,
    crosshairMarkerVisible: false,
  })

  const ema50 = chart.addSeries(LineSeries, {
    color: theme.ema50,
    lineWidth: 2,
    priceFormat,
    priceLineVisible: false,
    lastValueVisible: false,
    crosshairMarkerVisible: false,
  })

  const candles = chart.addSeries(CandlestickSeries, {
    upColor: theme.up,
    downColor: theme.down,
    borderUpColor: theme.up,
    borderDownColor: theme.down,
    wickUpColor: theme.up,
    wickDownColor: theme.down,
    priceFormat,
    lastValueVisible: true,
    priceLineVisible: false,
  })

  candles.priceScale().applyOptions({
    autoScale: true,
    scaleMargins: { top: 0.08, bottom: 0.08 },
    borderColor: theme.border,
  })

  const watermark = createTextWatermark(chart.panes()[0], {
    horzAlign: 'center',
    vertAlign: 'center',
    lines: [{
      text: '',
      color: 'rgba(19, 23, 34, 0.03)',
      fontSize: 40,
      fontStyle: 'bold',
      fontFamily: theme.font,
    }],
  })

  return { chart, candles, ema20, ema50, watermark }
}
