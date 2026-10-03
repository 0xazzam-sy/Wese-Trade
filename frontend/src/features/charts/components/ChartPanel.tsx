import { CandlestickChart as CandlesIcon } from 'lucide-react';

import { EmptyState } from '@/components/ui/EmptyState';
import { useChartData } from '@/features/charts/hooks/useChartData';
import { cn } from '@/lib/cn';
import { useChartStore } from '@/stores/chartStore';
import { useConnectionStore } from '@/stores/connectionStore';
import { type ChartId, useLayoutStore } from '@/stores/layoutStore';

import { CandlestickChart } from './CandlestickChart';
import { ChartHeader } from './ChartHeader';

const TITLES: Record<ChartId, string> = {
  primary: 'الرسم الرئيسي',
  secondary: 'الرسم الثانوي',
};

/** Container: wires stores + data hook to the presentational chart components. */
export function ChartPanel({ chartId, className }: { chartId: ChartId; className?: string }) {
  const selection = useChartStore((s) => s.charts[chartId]);
  const setSymbol = useChartStore((s) => s.setSymbol);
  const setTimeframe = useChartStore((s) => s.setTimeframe);
  const maximized = useLayoutStore((s) => s.maximizedChart === chartId);
  const toggleMaximized = useLayoutStore((s) => s.toggleMaximized);
  const connection = useConnectionStore((s) => s.state);
  const reconnect = useConnectionStore((s) => s.reconnect);
  const data = useChartData(selection.symbol, selection.timeframe);

  return (
    <section
      aria-label={TITLES[chartId]}
      className={cn('ns-panel @container flex min-h-0 min-w-0 flex-col overflow-hidden', className)}
    >
      <ChartHeader
        title={TITLES[chartId]}
        symbol={selection.symbol}
        timeframe={selection.timeframe}
        feed={data.feed}
        connection={connection}
        maximized={maximized}
        onSymbolChange={(symbol) => {
          setSymbol(chartId, symbol);
        }}
        onTimeframeChange={(timeframe) => {
          setTimeframe(chartId, timeframe);
        }}
        onReconnect={reconnect}
        onToggleMaximize={() => {
          toggleMaximized(chartId);
        }}
      />
      <div className="relative min-h-0 flex-1">
        <CandlestickChart candles={data.candles} meta={data.meta} />
        {data.candles.length === 0 && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center overflow-hidden">
            <EmptyState
              compact
              icon={<CandlesIcon className="size-5" />}
              title="لا توجد بيانات سوق بعد"
              description={
                <>
                  سيتم عرض شموع <span className="ns-ltr">{selection.symbol}</span> الحية بعد ربط
                  مزود بيانات BingX في المرحلة القادمة.
                </>
              }
            />
          </div>
        )}
      </div>
    </section>
  );
}
