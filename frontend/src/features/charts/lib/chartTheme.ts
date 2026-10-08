import {
  ColorType,
  CrosshairMode,
  type CandlestickSeriesPartialOptions,
  type ChartOptions,
  type DeepPartial,
} from 'lightweight-charts';

import { chartLocalization } from './timeFormat';

/** Chart colors resolved from CSS design tokens (canvas cannot read CSS variables itself). */
export interface ChartPalette {
  background: string;
  text: string;
  grid: string;
  border: string;
  crosshair: string;
  crosshairLabel: string;
  bull: string;
  bear: string;
  ema20: string;
  ema50: string;
  ema200: string;
}

function cssVar(styles: CSSStyleDeclaration, name: string, fallback: string): string {
  const value = styles.getPropertyValue(name).trim();
  return value || fallback;
}

export function readChartPalette(element: Element = document.documentElement): ChartPalette {
  const s = getComputedStyle(element);
  return {
    background: cssVar(s, '--ns-chart-bg', 'transparent'),
    text: cssVar(s, '--ns-chart-text', 'gray'),
    grid: cssVar(s, '--ns-chart-grid', 'transparent'),
    border: cssVar(s, '--ns-chart-border', 'gray'),
    crosshair: cssVar(s, '--ns-chart-crosshair', 'gray'),
    crosshairLabel: cssVar(s, '--ns-chart-crosshair-label', 'black'),
    bull: cssVar(s, '--ns-bull', 'green'),
    bear: cssVar(s, '--ns-bear', 'red'),
    ema20: cssVar(s, '--ns-warning', '#f5a524'),
    ema50: cssVar(s, '--ns-accent', '#22d3ee'),
    ema200: cssVar(s, '--ns-violet', '#a78bfa'),
  };
}

export function buildChartOptions(p: ChartPalette): DeepPartial<ChartOptions> {
  return {
    autoSize: true,
    layout: {
      background: { type: ColorType.Solid, color: p.background },
      textColor: p.text,
      fontFamily: "'IBM Plex Mono', ui-monospace, monospace",
      fontSize: 11,
      attributionLogo: true,
    },
    grid: {
      vertLines: { color: p.grid },
      horzLines: { color: p.grid },
    },
    rightPriceScale: { borderColor: p.border },
    timeScale: {
      borderColor: p.border,
      timeVisible: true,
      secondsVisible: false,
      tickMarkFormatter: chartLocalization.tickMarkFormatter,
    },
    crosshair: {
      mode: CrosshairMode.Normal,
      vertLine: { color: p.crosshair, labelBackgroundColor: p.crosshairLabel },
      horzLine: { color: p.crosshair, labelBackgroundColor: p.crosshairLabel },
    },
    localization: { timeFormatter: chartLocalization.timeFormatter, locale: 'en-US' },
  };
}

export function buildCandlestickOptions(p: ChartPalette): CandlestickSeriesPartialOptions {
  return {
    upColor: p.bull,
    downColor: p.bear,
    borderUpColor: p.bull,
    borderDownColor: p.bear,
    wickUpColor: p.bull,
    wickDownColor: p.bear,
    priceLineVisible: true,
  };
}
