import { describe, expect, it, vi } from 'vitest';

import { AnalysisOverlay, claimLabelRow, readOverlayPalette } from './AnalysisOverlay';
import { EMPTY_MODEL } from './overlayModel';

describe('AnalysisOverlay', () => {
  it('attaches as one series primitive and redraws on new models', () => {
    const overlay = new AnalysisOverlay();
    const requestUpdate = vi.fn();
    const series = {
      attachPrimitive: vi.fn((p: AnalysisOverlay) => {
        p.attached({ chart: {} as never, series: series as never, requestUpdate });
      }),
      detachPrimitive: vi.fn((p: AnalysisOverlay) => {
        p.detached();
      }),
    };
    overlay.attach({ chart: {} as never, series: series as never });
    expect(series.attachPrimitive).toHaveBeenCalledWith(overlay);
    expect(overlay.paneViews().map((v) => v.zOrder?.())).toEqual(['bottom', 'top']);
    const model = { ...EMPTY_MODEL, labels: [] };
    overlay.setModel(model, readOverlayPalette());
    expect(requestUpdate).toHaveBeenCalledTimes(1);
    expect(overlay.current).toBe(model);
    overlay.detach();
    expect(series.detachPrimitive).toHaveBeenCalledWith(overlay);
    overlay.setModel(EMPTY_MODEL, readOverlayPalette()); // detached: no redraw request
    expect(requestUpdate).toHaveBeenCalledTimes(1);
  });
});

describe('claimLabelRow (trade-plan label declutter)', () => {
  it('skips a label that would overlap one already drawn', () => {
    const taken: number[] = [];
    expect(claimLabelRow(taken, 100)).toBe(true); // Entry
    expect(claimLabelRow(taken, 105)).toBe(false); // too close
    expect(claimLabelRow(taken, 112)).toBe(true);
    expect(claimLabelRow(taken, 60)).toBe(true);
    expect(taken).toEqual([100, 112, 60]);
  });
});
