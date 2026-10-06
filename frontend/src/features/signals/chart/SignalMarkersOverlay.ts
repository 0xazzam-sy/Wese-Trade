import {
  createSeriesMarkers,
  type IChartApi,
  type ISeriesMarkersPluginApi,
  type MouseEventParams,
  type SeriesMarker,
  type Time,
} from 'lightweight-charts';

import type { OverlayPalette } from '@/features/analysis/overlays/AnalysisOverlay';
import type { ChartOverlay, OverlayContext } from '@/features/charts/overlays/types';

import type { MarkerSpec } from './chartSignals';

export interface MarkerPointer {
  id: string;
  /** Pointer position in viewport coordinates (the details card is fixed-positioned). */
  x: number;
  y: number;
}

/** `#rrggbb` → rgba with alpha; other CSS colors are returned unchanged. */
export function withAlpha(color: string, alpha: number): string {
  const m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(color.trim());
  if (!m) return color;
  const [r, g, b] = [m[1], m[2], m[3]].map((h) => parseInt(h ?? '0', 16));
  return `rgba(${String(r)}, ${String(g)}, ${String(b)}, ${String(alpha)})`;
}

/** Confirmed signals stand out (larger, full color); closed history stays visible but muted. */
export function toSeriesMarkers(
  specs: readonly MarkerSpec[],
  palette: Pick<OverlayPalette, 'bull' | 'bear'>,
): SeriesMarker<Time>[] {
  return specs.map((m) => {
    const base = m.side === 'long' ? palette.bull : palette.bear;
    return {
      id: m.id,
      time: m.time as Time,
      position: m.position,
      shape: m.shape,
      color: m.active ? base : withAlpha(base, 0.5),
      text: m.text,
      size: m.active ? 2 : 1.4,
    };
  });
}

/**
 * BUY/SELL markers of confirmed forward-test signals (lightweight-charts series markers).
 * Drawn above the analysis annotations; hover/click report the marker for its details card.
 */
export class SignalMarkersOverlay implements ChartOverlay {
  readonly id = 'signal-markers';
  readonly kind = 'signal-markers' as const;
  private plugin: ISeriesMarkersPluginApi<Time> | null = null;
  private chart: IChartApi | null = null;
  private markers: SeriesMarker<Time>[] = [];
  private ids = new Set<string>();
  private pinned: MarkerPointer | null = null;

  constructor(
    private readonly onPointer: (pointer: MarkerPointer | null) => void = () => undefined,
  ) {}

  attach({ chart, series }: OverlayContext): void {
    this.chart = chart;
    // 'top': BUY/SELL markers have priority over every analysis annotation.
    this.plugin = createSeriesMarkers(series, this.markers, { zOrder: 'top' });
    chart.subscribeCrosshairMove(this.onMove);
    chart.subscribeClick(this.onClick);
  }

  detach(): void {
    this.chart?.unsubscribeCrosshairMove(this.onMove);
    this.chart?.unsubscribeClick(this.onClick);
    this.plugin?.detach();
    this.plugin = null;
    this.chart = null;
  }

  setMarkers(markers: SeriesMarker<Time>[]): void {
    this.markers = markers;
    this.ids = new Set(markers.map((m) => String(m.id)));
    if (this.pinned && !this.ids.has(this.pinned.id)) this.unpin();
    this.plugin?.setMarkers(markers);
  }

  /** Marker id under the pointer: the chart's hit test, else the marker on the hovered bar. */
  private hit(param: MouseEventParams): MarkerPointer | null {
    if (!param.point) return null;
    const objectId = param.hoveredInfo?.objectId;
    const hovered = typeof objectId === 'string' ? objectId : null;
    const id =
      hovered && this.ids.has(hovered)
        ? hovered
        : (this.markers.find((m) => m.time === param.time)?.id ?? null);
    if (!id) return null;
    const rect = this.chart?.chartElement().getBoundingClientRect();
    return { id, x: (rect?.left ?? 0) + param.point.x, y: (rect?.top ?? 0) + param.point.y };
  }

  private unpin(): void {
    this.pinned = null;
    this.onPointer(null);
  }

  private readonly onMove = (param: MouseEventParams): void => {
    if (this.pinned) return;
    this.onPointer(this.hit(param));
  };

  private readonly onClick = (param: MouseEventParams): void => {
    const pointer = this.hit(param);
    if (pointer && this.pinned?.id !== pointer.id) {
      this.pinned = pointer;
      this.onPointer(pointer);
    } else {
      this.unpin();
    }
  };
}
