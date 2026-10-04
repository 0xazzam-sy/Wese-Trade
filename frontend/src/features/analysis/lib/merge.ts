import type { AnalysisSnapshot } from '@/types/analysis';

/**
 * Applies one `analysis.update` to the current snapshot of a chart.
 *
 * - `full` replaces everything (sent on subscribe and at every candle close).
 * - `live` only refreshes forming-candle fields (price, developing features, premium/
 *   discount position, OTE). It is applied only on top of a full snapshot of the SAME
 *   symbol/timeframe and the SAME closed candle; otherwise it is stale and ignored.
 * - An update for another symbol/timeframe is always ignored (late event after a switch).
 */
export function applyAnalysisUpdate(
  current: AnalysisSnapshot | null,
  update: AnalysisSnapshot,
  expected: { symbol: string; timeframe: string },
): AnalysisSnapshot | null {
  if (update.symbol !== expected.symbol || update.timeframe !== expected.timeframe) {
    return current;
  }
  if (update.kind !== 'live') {
    if (
      current?.analysis_ready &&
      update.analysis_ready &&
      current.candle_time !== null &&
      update.candle_time !== null &&
      update.candle_time < current.candle_time
    ) {
      return current; // an older full snapshot arrived late
    }
    return update;
  }
  if (!current?.analysis_ready || current.candle_time !== update.candle_time) return current;
  const merged: AnalysisSnapshot = {
    ...current,
    price: update.price,
    forming_time: update.forming_time,
    forming_candle: update.forming_candle ?? null,
    developing: update.developing ?? null,
    premium_discount: update.premium_discount ?? current.premium_discount ?? null,
    ote: update.ote ?? null,
  };
  if (update.generated_at !== undefined) merged.generated_at = update.generated_at;
  return merged;
}
