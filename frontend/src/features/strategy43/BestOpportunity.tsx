import { cn } from '@/lib/cn';
import { useAnalysisStore } from '@/stores/analysisStore';
import { useChartStore } from '@/stores/chartStore';
import type { Timeframe } from '@/types/market';
import type { OpportunityDTO } from '@/types/strategy43';

import { bestText, S43_AR } from './labels';

/**
 * Shown under «لا توجد فرصة مناسبة حالياً»: the best open Strategy 4.3
 * opportunity of the same symbol on another primary timeframe. Click to open it.
 */
export function BestOpportunity({
  best,
  timeframe,
}: {
  best: OpportunityDTO | null | undefined;
  timeframe: string;
}) {
  const focused = useAnalysisStore((s) => s.focused);
  const setTimeframe = useChartStore((s) => s.setTimeframe);
  if (!best || best.timeframe === timeframe) {
    return (
      <p className="text-fg-subtle text-2xs" data-testid="best-opportunity" data-empty="true">
        {S43_AR.noneOther}
      </p>
    );
  }
  return (
    <button
      type="button"
      data-testid="best-opportunity"
      data-timeframe={best.timeframe}
      onClick={() => {
        setTimeframe(focused, best.timeframe as Timeframe);
      }}
      className="hover:bg-sunken flex w-full min-w-0 items-center gap-1.5 rounded-md px-1 py-0.5 text-start text-xs"
      title="فتح الفريم"
    >
      <span className="text-fg-subtle shrink-0">{S43_AR.bestOther}</span>
      <span
        className={cn(
          'ns-ltr shrink-0 font-semibold',
          best.side === 'BUY' ? 'text-bull' : 'text-bear',
        )}
      >
        {bestText(best)}
      </span>
      <span className="text-fg-subtle truncate">{best.state_ar}</span>
    </button>
  );
}
