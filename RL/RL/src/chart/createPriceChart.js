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

export function createPriceChart(container) {
  const chart = createChart(container, {
    autoSize: true,
    layout: {
      background: { type: ColorType.Solid, color: theme.background },
      textColor: theme.text,
      fontFamily: theme.font,
      fontSize: 12,
      attributionLogo: true,
      panes: {
        enableResize: true,
        separatorColor: theme.border,
        separatorHoverColor: 'rgba(41, 98, 255, 0.2)',
      },
    },
    grid: {
      vertLines: { color: theme.grid },
      horzLines: { color: theme.grid },
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
    rightPriceScale: { borderColor: theme.border },
    leftPriceScale: { visible: false },
    timeScale: {
      borderColor: theme.border,
      timeVisible: true,
      secondsVisible: false,
      rightOffset: 0,
      barSpacing: 8,
      minBarSpacing: 0.05,
      fixLeftEdge: true,
      fixRightEdge: true,
    },
    localization: {
      locale: 'en-GB',
      dateFormat: "dd MMM 'yy",
    },
    handleScroll: { vertTouchDrag: false },
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
    priceLineVisible: true,
  })

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

  candles.priceScale().applyOptions({
    scaleMargins: { top: 0.12, bottom: 0.06 },
    borderColor: theme.border,
  })

  const watermark = createTextWatermark(chart.panes()[0], {
    horzAlign: 'center',
    vertAlign: 'center',
    lines: [{
      text: '',
      color: theme.watermark,
      fontSize: 52,
      fontStyle: 'bold',
      fontFamily: theme.font,
    }],
  })

  return { chart, candles, ema20, ema50, watermark }
}
