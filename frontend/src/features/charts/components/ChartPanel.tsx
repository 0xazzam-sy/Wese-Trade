import { useCallback, useEffect, useRef } from 'react';

import { useMarketChart } from '@/features/charts/hooks/useMarketChart';
import type { ChartController } from '@/features/charts/lib/ChartController';
import { useSymbolMap } from '@/features/markets/queries';
import { cn } from '@/lib/cn';
import { useChartStore } from '@/stores/chartStore';
import { useConnectionStore } from '@/stores/connectionStore';
import { type ChartId, useLayoutStore } from '@/stores/layoutStore';
import { useMarketStore } from '@/stores/marketStore';

import { CandlestickChart } from './CandlestickChart';
import { ChartBodyState } from './ChartBodyState';
import { ChartHeader } from './ChartHeader';
import { feedIndicator } from '../lib/feedIndicator';

const TITLES: Record<ChartId, string> = {
  primary: 'الرسم الرئيسي',
  secondary: 'الرسم الثانوي',
};

/**
 * One independent chart. Its loading/error state never affects the other chart.
 * High-frequency data goes straight to the ChartController; React only sees status changes.
 */
export function ChartPanel({ chartId, className }: { chartId: ChartId; className?: string }) {
  const selection = useChartStore((s) => s.charts[chartId]);
  const setSymbol = useChartStore((s) => s.setSymbol);
  const setTimeframe = useChartStore((s) => s.setTimeframe);
  const maximized = useLayoutStore((s) => s.maximizedChart === chartId);
  const toggleMaximized = useLayoutStore((s) => s.toggleMaximized);
  const appConnection = useConnectionStore((s) => s.state);
  const feed = useMarketStore((s) => s.feed);
  const symbols = useSymbolMap();
  const meta = symbols.get(selection.symbol);
  const controllerRef = useRef<ChartController | null>(null);
  const onController = useCallback((controller: ChartController | null) => {
    controllerRef.current = controller;
  }, []);
  const { load, stream, reload } = useMarketChart(
    controllerRef,
    selection.symbol,
    selection.timeframe,
    meta,
  );
  const indicator = feedIndicator(appConnection, feed, stream, load);

  // Auto-retry while the backend is still loading exchange metadata.
  useEffect(() => {
    if (load.status !== 'error' || load.code !== 'loading_metadata') return;
    const timer = setTimeout(reload, 5000);
    return () => {
      clearTimeout(timer);
    };
  }, [load, reload]);

  return (
    <section
      aria-label={TITLES[chartId]}
      data-chart={chartId}
      data-symbol={selection.symbol}
      data-timeframe={selection.timeframe}
      data-load={load.status}
      className={cn('ns-panel @container flex min-h-0 min-w-0 flex-col overflow-hidden', className)}
    >
      <ChartHeader
        title={TITLES[chartId]}
        symbol={selection.symbol}
        timeframe={selection.timeframe}
        meta={meta}
        indicator={indicator}
        reloading={load.status === 'loading'}
        maximized={maximized}
        onSymbolChange={(symbol) => {
          setSymbol(chartId, symbol);
        }}
        onTimeframeChange={(timeframe) => {
          setTimeframe(chartId, timeframe);
        }}
        onReload={reload}
        onToggleMaximize={() => {
          toggleMaximized(chartId);
        }}
      />
      <div className="relative min-h-0 flex-1">
        <CandlestickChart onController={onController} />
        <ChartBodyState load={load} symbol={selection.symbol} onRetry={reload} />
      </div>
    </section>
  );
}
