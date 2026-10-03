import type { ISeriesApi, ISeriesPrimitive, SeriesType } from 'lightweight-charts';

import type { ChartOverlay, OverlayContext, OverlayKind } from './types';

/**
 * Base adapter for overlays implemented as lightweight-charts v5 series primitives
 * (`series.attachPrimitive`). Concrete primitives (order blocks, FVGs, ...) come later.
 */
export class SeriesPrimitiveOverlay implements ChartOverlay {
  private series: ISeriesApi<SeriesType> | null = null;

  constructor(
    readonly id: string,
    readonly kind: OverlayKind,
    private readonly primitive: ISeriesPrimitive,
  ) {}

  attach({ series }: OverlayContext): void {
    series.attachPrimitive(this.primitive);
    this.series = series;
  }

  detach(): void {
    this.series?.detachPrimitive(this.primitive);
    this.series = null;
  }
}
