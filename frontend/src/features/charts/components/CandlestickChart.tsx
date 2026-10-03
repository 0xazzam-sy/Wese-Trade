import {
  CandlestickSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
} from 'lightweight-charts';
import { useEffect, useRef } from 'react';

import { type ChartCandle, priceFormatFor } from '@/features/charts/lib/candles';
import {
  buildCandlestickOptions,
  buildChartOptions,
  readChartPalette,
} from '@/features/charts/lib/chartTheme';
import { OverlayController } from '@/features/charts/overlays/OverlayController';
import type { ChartOverlay } from '@/features/charts/overlays/types';
import { cn } from '@/lib/cn';
import { useThemeStore } from '@/stores/themeStore';
import type { SymbolMeta } from '@/types/market';

interface CandlestickChartProps {
  candles: readonly ChartCandle[];
  meta: SymbolMeta | null;
  overlays?: readonly ChartOverlay[];
  className?: string;
}

const NO_OVERLAYS: readonly ChartOverlay[] = [];

/**
 * Presentation-only wrapper around lightweight-charts v5.
 * Owns the chart instance lifecycle; receives fully prepared data via props.
 */
export function CandlestickChart({
  candles,
  meta,
  overlays = NO_OVERLAYS,
  className,
}: CandlestickChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const overlaysRef = useRef<OverlayController | null>(null);
  const theme = useThemeStore((s) => s.theme);

  // Create / destroy the chart instance.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const palette = readChartPalette();
    const chart = createChart(container, buildChartOptions(palette));
    const series = chart.addSeries(CandlestickSeries, buildCandlestickOptions(palette));
    chartRef.current = chart;
    seriesRef.current = series;
    overlaysRef.current = new OverlayController({ chart, series });

    return () => {
      overlaysRef.current?.clear();
      overlaysRef.current = null;
      seriesRef.current = null;
      chartRef.current = null;
      chart.remove();
    };
  }, []);

  // Re-theme when the app theme changes (CSS variables are already updated).
  useEffect(() => {
    const palette = readChartPalette();
    chartRef.current?.applyOptions(buildChartOptions(palette));
    seriesRef.current?.applyOptions(buildCandlestickOptions(palette));
  }, [theme]);

  // Price precision / tick size from exchange metadata.
  useEffect(() => {
    const priceFormat = priceFormatFor(meta);
    if (priceFormat) seriesRef.current?.applyOptions({ priceFormat });
  }, [meta]);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    series.setData([...candles]);
    if (candles.length > 0) chartRef.current?.timeScale().fitContent();
  }, [candles]);

  useEffect(() => {
    overlaysRef.current?.sync(overlays);
  }, [overlays]);

  // Charts are conventionally LTR (time flows left → right) even in an RTL app.
  return <div ref={containerRef} dir="ltr" className={cn('size-full', className)} />;
}
