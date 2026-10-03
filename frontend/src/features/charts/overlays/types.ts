import type { IChartApi, ISeriesApi, SeriesType } from 'lightweight-charts';

/**
 * Overlay architecture for future analysis visuals. Overlays only DRAW data computed by
 * the backend — no trading logic may live in an overlay.
 *
 * Planned kinds (none implemented in phase 1):
 *  - signal-markers   → BUY/SELL markers      (v5 `createSeriesMarkers`)
 *  - order-block      → rectangles            (ISeriesPrimitive)
 *  - fair-value-gap   → rectangles            (ISeriesPrimitive)
 *  - structure-break  → BOS / CHoCH labels    (ISeriesPrimitive)
 *  - liquidity-level  → horizontal levels     (ISeriesPrimitive / price lines)
 *  - trade-plan       → Entry / SL / TP lines (`series.createPriceLine`)
 */
export type OverlayKind =
  | 'signal-markers'
  | 'order-block'
  | 'fair-value-gap'
  | 'structure-break'
  | 'liquidity-level'
  | 'trade-plan';

export interface OverlayContext {
  chart: IChartApi;
  series: ISeriesApi<SeriesType>;
}

export interface ChartOverlay {
  /** Stable id: overlays are diffed by id when the overlay list changes. */
  readonly id: string;
  readonly kind: OverlayKind;
  attach(context: OverlayContext): void;
  detach(): void;
}
