import { CandlestickSeries, createChart, type IChartApi, LineSeries } from 'lightweight-charts';
import { useEffect, useRef } from 'react';

import { ChartController } from '@/features/charts/lib/ChartController';
import {
  buildCandlestickOptions,
  buildChartOptions,
  readChartPalette,
} from '@/features/charts/lib/chartTheme';
import { OverlayController } from '@/features/charts/overlays/OverlayController';
import type { ChartOverlay } from '@/features/charts/overlays/types';
import { cn } from '@/lib/cn';
import { useThemeStore } from '@/stores/themeStore';

interface CandlestickChartProps {
  /** Receives the controller once the chart exists (null on unmount). Must be stable. */
  onController: (controller: ChartController | null) => void;
  overlays?: readonly ChartOverlay[];
  /** EMA 20 / 50 / 200 lines visible (overlay toggle). */
  showEma?: boolean;
  className?: string;
}

const NO_OVERLAYS: readonly ChartOverlay[] = [];

/** EMA 20 / 50 / 200 colors from the chart palette (fast = accent, slow = muted). */
function emaColors(palette: ReturnType<typeof readChartPalette>): string[] {
  return [palette.ema20, palette.ema50, palette.ema200];
}
/** Initial view after a history load: the most recent bars, so analysis overlays stay legible. */
export const INITIAL_VISIBLE_BARS = 150;

/**
 * Presentation-only wrapper around lightweight-charts v5. The chart instance is created
 * once; data flows in imperatively through ChartController (no React re-render per tick).
 */
export function CandlestickChart({
  onController,
  overlays = NO_OVERLAYS,
  showEma = true,
  className,
}: CandlestickChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const overlaysRef = useRef<OverlayController | null>(null);
  const controllerRef = useRef<ChartController | null>(null);
  const seriesOptionsRef = useRef<((palette: ReturnType<typeof readChartPalette>) => void) | null>(
    null,
  );
  const theme = useThemeStore((s) => s.theme);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const palette = readChartPalette();
    const chart = createChart(container, buildChartOptions(palette));
    const series = chart.addSeries(CandlestickSeries, buildCandlestickOptions(palette));
    const emaLines = emaColors(palette).map((color) =>
      chart.addSeries(LineSeries, {
        color,
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      }),
    );
    chartRef.current = chart;
    const resetView = () => {
      // A dragged/zoomed price axis turns auto-scale off; a new context must never keep
      // the previous symbol's price range.
      series.priceScale().setAutoScale(true);
      chart.timeScale().resetTimeScale();
    };
    const controller = new ChartController(
      series,
      (count) => {
        series.priceScale().setAutoScale(true);
        if (count <= INITIAL_VISIBLE_BARS) {
          chart.timeScale().fitContent();
          return;
        }
        chart
          .timeScale()
          .setVisibleLogicalRange({ from: count - INITIAL_VISIBLE_BARS, to: count + 4 });
      },
      resetView,
      emaLines,
    );
    controllerRef.current = controller;
    seriesOptionsRef.current = (p) => {
      series.applyOptions(buildCandlestickOptions(p));
      emaColors(p).forEach((color, i) => emaLines[i]?.applyOptions({ color }));
    };
    overlaysRef.current = new OverlayController({ chart, series });
    onController(controller);

    // Read-only diagnostics for E2E/QA: what the chart is really showing (visible price
    // range vs. the last candle). Never read by the app itself.
    const inspect = window.setInterval(() => {
      const range = series.priceScale().getVisibleRange();
      const data = series.data();
      const last = data[data.length - 1];
      container.dataset.priceRange = range ? `${String(range.from)}:${String(range.to)}` : '';
      container.dataset.lastClose = last && 'close' in last ? String(last.close) : '';
      container.dataset.bars = String(data.length);
    }, 500);

    return () => {
      window.clearInterval(inspect);
      overlaysRef.current?.clear();
      overlaysRef.current = null;
      onController(null);
      controllerRef.current = null;
      chartRef.current = null;
      chart.remove();
    };
  }, [onController]);

  useEffect(() => {
    const palette = readChartPalette();
    chartRef.current?.applyOptions(buildChartOptions(palette));
    seriesOptionsRef.current?.(palette);
  }, [theme]);

  useEffect(() => {
    overlaysRef.current?.sync(overlays);
  }, [overlays]);

  useEffect(() => {
    controllerRef.current?.setEmaVisible(showEma);
  }, [showEma]);

  // Charts are conventionally LTR (time flows left → right) even in an RTL app.
  return <div ref={containerRef} dir="ltr" className={cn('size-full', className)} />;
}
