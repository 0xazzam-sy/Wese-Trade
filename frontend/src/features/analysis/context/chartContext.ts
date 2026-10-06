import { useAnalysisStore } from '@/stores/analysisStore';
import { useChartStore } from '@/stores/chartStore';
import type { ChartId } from '@/stores/layoutStore';
import type { AnalysisSnapshot } from '@/types/analysis';
import type { Timeframe } from '@/types/market';
import type { SignalView } from '@/types/signal';

/**
 * ONE canonical chart context per chart: the symbol/timeframe selected in the chart store.
 * Everything describing a chart (header, candles, analysis panel, signal state, trade plan,
 * markers) must refer to exactly this context. Data for any other symbol/timeframe — e.g. a
 * late update after a switch — is treated as "not loaded yet", never displayed.
 */
export interface ChartContext {
  chartId: ChartId;
  symbol: string;
  timeframe: Timeframe;
}

export function belongsTo(
  data: { symbol: string; timeframe: string } | null | undefined,
  context: { symbol: string; timeframe: string },
): boolean {
  return data?.symbol === context.symbol && data.timeframe === context.timeframe;
}

export function contextualSnapshot(
  snapshot: AnalysisSnapshot | null,
  context: ChartContext,
): AnalysisSnapshot | null {
  return belongsTo(snapshot, context) ? snapshot : null;
}

export function contextualSignal(
  view: SignalView | null,
  context: ChartContext,
): SignalView | null {
  return belongsTo(view, context) ? view : null;
}

/** The focused chart's canonical context with only the data that belongs to it. */
export function useFocusedChartContext(): {
  context: ChartContext;
  snapshot: AnalysisSnapshot | null;
  view: SignalView | null;
} {
  const chartId = useAnalysisStore((s) => s.focused);
  const selection = useChartStore((s) => s.charts[chartId]);
  const rawSnapshot = useAnalysisStore((s) => s.byChart[chartId]);
  const rawView = useAnalysisStore((s) => s.signals[chartId]);
  const context = { chartId, symbol: selection.symbol, timeframe: selection.timeframe };
  return {
    context,
    snapshot: contextualSnapshot(rawSnapshot, context),
    view: contextualSignal(rawView, context),
  };
}
