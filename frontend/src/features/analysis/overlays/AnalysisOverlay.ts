import type {
  IChartApi,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  PrimitivePaneViewZOrder,
  SeriesType,
  Time,
} from 'lightweight-charts';

import type { ChartOverlay, OverlayContext } from '@/features/charts/overlays/types';

import {
  EMPTY_MODEL,
  type LineKind,
  type OverlayModel,
  type Tone,
  type ZoneKind,
} from './overlayModel';

type Target = Parameters<IPrimitivePaneRenderer['draw']>[0];
type Ctx = CanvasRenderingContext2D;

/** Colors resolved from design tokens (canvas cannot read CSS variables). */
export interface OverlayPalette {
  bull: string;
  bear: string;
  neutral: string;
  accent: string;
  violet: string;
  warning: string;
  text: string;
}

function cssVar(styles: CSSStyleDeclaration, name: string, fallback: string): string {
  return styles.getPropertyValue(name).trim() || fallback;
}

export function readOverlayPalette(element: Element = document.documentElement): OverlayPalette {
  const s = getComputedStyle(element);
  return {
    bull: cssVar(s, '--ns-bull', '#10b981'),
    bear: cssVar(s, '--ns-bear', '#e5484d'),
    neutral: cssVar(s, '--ns-neutral', '#7d8ca3'),
    accent: cssVar(s, '--ns-accent', '#22d3ee'),
    violet: cssVar(s, '--ns-violet', '#a78bfa'),
    warning: cssVar(s, '--ns-warning', '#f5a524'),
    text: cssVar(s, '--ns-chart-text', '#7f8ca2'),
  };
}

const ZONE_STYLE: Record<ZoneKind, { color: keyof OverlayPalette; alpha: number; border: number }> =
  {
    'fvg-bull': { color: 'bull', alpha: 0.1, border: 0 },
    'fvg-bear': { color: 'bear', alpha: 0.1, border: 0 },
    'ob-bull': { color: 'bull', alpha: 0.16, border: 0.55 },
    'ob-bear': { color: 'bear', alpha: 0.16, border: 0.55 },
    premium: { color: 'bear', alpha: 0.05, border: 0 },
    discount: { color: 'bull', alpha: 0.05, border: 0 },
    equilibrium: { color: 'neutral', alpha: 0.06, border: 0 },
    ote: { color: 'violet', alpha: 0.12, border: 0.5 },
  };

const LINE_COLOR: Record<LineKind, keyof OverlayPalette> = {
  'liq-buy': 'accent',
  'liq-sell': 'accent',
  'bos-bull': 'bull',
  'bos-bear': 'bear',
  protected: 'warning',
  'eq-line': 'neutral',
};

const TONE_COLOR: Record<Tone, keyof OverlayPalette> = {
  bull: 'bull',
  bear: 'bear',
  neutral: 'neutral',
  accent: 'accent',
  violet: 'violet',
  warning: 'warning',
};

const FONT = '500 10px "IBM Plex Mono", ui-monospace, monospace';
const ARABIC_FONT = '500 10px "IBM Plex Sans Arabic", system-ui, sans-serif';

class Renderer implements IPrimitivePaneRenderer {
  constructor(
    private readonly owner: AnalysisOverlay,
    private readonly layer: 'zones' | 'marks',
  ) {}

  draw(target: Target): void {
    target.useMediaCoordinateSpace(({ context, mediaSize }) => {
      this.owner.render(context, mediaSize.width, this.layer);
    });
  }
}

class View implements IPrimitivePaneView {
  private readonly paneRenderer: Renderer;

  constructor(
    owner: AnalysisOverlay,
    private readonly order: PrimitivePaneViewZOrder,
    layer: 'zones' | 'marks',
  ) {
    this.paneRenderer = new Renderer(owner, layer);
  }

  zOrder(): PrimitivePaneViewZOrder {
    return this.order;
  }

  renderer(): IPrimitivePaneRenderer {
    return this.paneRenderer;
  }
}

/**
 * Draws backend analysis (structure, liquidity, FVG, OB, premium/discount, OTE) on one
 * chart as a single series primitive. Zones render beneath candles, lines/labels above.
 * The overlay only draws: it never computes analysis.
 */
export class AnalysisOverlay implements ChartOverlay, ISeriesPrimitive {
  readonly id = 'analysis';
  readonly kind = 'analysis' as const;
  private model: OverlayModel = EMPTY_MODEL;
  private palette: OverlayPalette | null = null;
  private chart: IChartApi | null = null;
  private series: ISeriesApi<SeriesType> | null = null;
  private requestUpdate: (() => void) | null = null;
  private readonly views: View[] = [
    new View(this, 'bottom', 'zones'),
    new View(this, 'top', 'marks'),
  ];

  // --- ChartOverlay ---------------------------------------------------------------
  attach({ series }: OverlayContext): void {
    series.attachPrimitive(this);
  }

  detach(): void {
    this.series?.detachPrimitive(this);
  }

  // --- ISeriesPrimitive -------------------------------------------------------------
  attached(param: {
    chart: IChartApi;
    series: ISeriesApi<SeriesType>;
    requestUpdate: () => void;
  }): void {
    this.chart = param.chart;
    this.series = param.series;
    this.requestUpdate = param.requestUpdate;
  }

  detached(): void {
    this.chart = null;
    this.series = null;
    this.requestUpdate = null;
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return this.views;
  }

  // --- data -------------------------------------------------------------------------
  setModel(model: OverlayModel, palette: OverlayPalette): void {
    this.model = model;
    this.palette = palette;
    this.requestUpdate?.();
  }

  get current(): OverlayModel {
    return this.model;
  }

  // --- drawing ----------------------------------------------------------------------
  private x(
    time: number,
    width: number,
    bounds: { first: number; last: number } | null,
  ): number | null {
    const scale = this.chart?.timeScale();
    if (!scale || !bounds) return null;
    const direct = scale.timeToCoordinate(time as Time);
    if (direct !== null) return direct;
    if (time <= bounds.first) return scale.timeToCoordinate(bounds.first as Time) ?? 0;
    return scale.timeToCoordinate(bounds.last as Time) ?? width;
  }

  private bounds(): { first: number; last: number } | null {
    const data = this.series?.data() ?? [];
    const first = data[0]?.time;
    const last = data[data.length - 1]?.time;
    if (typeof first !== 'number' || typeof last !== 'number') return null;
    return { first, last };
  }

  render(ctx: Ctx, width: number, layer: 'zones' | 'marks'): void {
    const series = this.series;
    const palette = this.palette;
    if (!series || !palette) return;
    const bounds = this.bounds();
    const y = (price: number) => series.priceToCoordinate(price);
    ctx.save();
    if (layer === 'zones') {
      for (const zone of this.model.zones) {
        const x1 = this.x(zone.from, width, bounds);
        const yTop = y(zone.top);
        const yBottom = y(zone.bottom);
        if (x1 === null || yTop === null || yBottom === null) continue;
        const x2 = zone.to === null ? width : (this.x(zone.to, width, bounds) ?? width);
        const style = ZONE_STYLE[zone.kind];
        const color = palette[style.color];
        const h = Math.max(1, yBottom - yTop);
        ctx.globalAlpha = style.alpha * (zone.faded ? 0.5 : 1);
        ctx.fillStyle = color;
        ctx.fillRect(x1, yTop, Math.max(1, x2 - x1), h);
        if (style.border > 0) {
          ctx.globalAlpha = style.border * (zone.faded ? 0.5 : 1);
          ctx.strokeStyle = color;
          ctx.lineWidth = 1;
          ctx.strokeRect(Math.round(x1) + 0.5, Math.round(yTop) + 0.5, Math.max(1, x2 - x1), h);
        }
        if (zone.label && h >= 9) {
          ctx.globalAlpha = zone.faded ? 0.45 : 0.85;
          ctx.fillStyle = color;
          ctx.font = FONT;
          ctx.textBaseline = 'top';
          ctx.textAlign = 'left';
          ctx.fillText(zone.label, x1 + 3, yTop + 1);
        }
      }
    } else {
      for (const line of this.model.lines) {
        const x1 = this.x(line.from, width, bounds);
        const py = y(line.price);
        if (x1 === null || py === null) continue;
        const x2 = line.to === null ? width : (this.x(line.to, width, bounds) ?? width);
        const color = palette[LINE_COLOR[line.kind]];
        ctx.globalAlpha = line.faded ? 0.4 : 0.85;
        ctx.strokeStyle = color;
        ctx.lineWidth = 1;
        ctx.setLineDash(line.dashed ? [4, 3] : []);
        ctx.beginPath();
        ctx.moveTo(x1, Math.round(py) + 0.5);
        ctx.lineTo(x2, Math.round(py) + 0.5);
        ctx.stroke();
        if (line.label) {
          ctx.setLineDash([]);
          ctx.fillStyle = color;
          ctx.font = /[؀-ۿ]/.test(line.label) ? ARABIC_FONT : FONT;
          ctx.textAlign = 'right';
          ctx.textBaseline = 'bottom';
          ctx.fillText(line.label, Math.min(x2, width) - 4, py - 2);
        }
      }
      ctx.setLineDash([]);
      ctx.textAlign = 'center';
      ctx.font = FONT;
      for (const label of this.model.labels) {
        const px = this.x(label.time, width, bounds);
        const py = y(label.price);
        if (px === null || py === null) continue;
        ctx.globalAlpha = label.faded ? 0.45 : 0.9;
        ctx.fillStyle = palette[TONE_COLOR[label.tone]];
        ctx.textBaseline = label.position === 'above' ? 'bottom' : 'top';
        ctx.fillText(label.text, px, label.position === 'above' ? py - 4 : py + 4);
      }
    }
    ctx.restore();
  }
}
