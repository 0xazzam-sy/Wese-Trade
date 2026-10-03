import type { ChartOverlay, OverlayContext } from './types';

/** Attaches/detaches overlays on a chart, diffing by overlay id. */
export class OverlayController {
  private readonly attached = new Map<string, ChartOverlay>();

  constructor(private readonly context: OverlayContext) {}

  sync(overlays: readonly ChartOverlay[]): void {
    const next = new Map(overlays.map((o) => [o.id, o]));
    for (const [id, overlay] of this.attached) {
      if (next.get(id) !== overlay) {
        overlay.detach();
        this.attached.delete(id);
      }
    }
    for (const [id, overlay] of next) {
      if (!this.attached.has(id)) {
        overlay.attach(this.context);
        this.attached.set(id, overlay);
      }
    }
  }

  clear(): void {
    this.attached.forEach((overlay) => {
      overlay.detach();
    });
    this.attached.clear();
  }
}
