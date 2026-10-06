import { CandlestickSeries, createChart, type IChartApi } from 'lightweight-charts';
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
  className?: string;
}

const NO_OVERLAYS: readonly ChartOverlay[] = [];
/** Initial view after a history load: the most recent bars, so analysis overlays stay legible. */
export const INITIAL_VISIBLE_BARS = 150;

/**
 * Presentation-only wrapper around lightweight-charts v5. The chart instance is created
 * once; data flows in imperatively through ChartController (no React re-render per tick).
 */
export function CandlestickChart({
  onController,
  overlays = NO_OVERLAYS,
  className,
}: CandlestickChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const overlaysRef = useRef<OverlayController | null>(null);
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
    );
    seriesOptionsRef.current = (p) => {
      series.applyOptions(buildCandlestickOptions(p));
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

  // Charts are conventionally LTR (time flows left → right) even in an RTL app.
  return <div ref={containerRef} dir="ltr" className={cn('size-full', className)} />;
}
