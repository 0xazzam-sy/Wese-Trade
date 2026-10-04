import { describe, expect, it } from 'vitest';

import { DEFAULT_OVERLAYS, type OverlayToggles } from '@/stores/overlayStore';
import { notReady, readySnapshot } from '@/test/analysisFixture';

import { buildOverlayModel } from './overlayModel';

const ALL_ON: OverlayToggles = {
  structure: true,
  liquidity: true,
  fvg: true,
  orderBlocks: true,
  premiumDiscount: true,
  ote: true,
};
const ALL_OFF: OverlayToggles = {
  structure: false,
  liquidity: false,
  fvg: false,
  orderBlocks: false,
  premiumDiscount: false,
  ote: false,
};

describe('buildOverlayModel', () => {
  it('draws nothing until analysis is ready', () => {
    expect(buildOverlayModel(null, ALL_ON).zones).toEqual([]);
    expect(buildOverlayModel(notReady('loading_history'), ALL_ON).labels).toEqual([]);
  });

  it('respects every toggle', () => {
    const snapshot = readySnapshot();
    const none = buildOverlayModel(snapshot, ALL_OFF);
    expect(none.zones.length + none.lines.length + none.labels.length).toBe(0);
    const all = buildOverlayModel(snapshot, ALL_ON);
    const zoneKinds = new Set(all.zones.map((z) => z.kind));
    expect(zoneKinds).toEqual(new Set(['fvg-bull', 'ob-bull', 'premium', 'discount', 'ote']));
    expect(all.labels.some((l) => l.text === 'BOS')).toBe(true);
    expect(all.labels.some((l) => l.text === 'HH')).toBe(true);
    expect(all.lines.some((l) => l.label === 'EQH')).toBe(true);
    expect(all.lines.some((l) => l.kind === 'protected')).toBe(true);
  });

  it('keeps the default chart readable (premium/discount and OTE off)', () => {
    const kinds = buildOverlayModel(readySnapshot(), DEFAULT_OVERLAYS).zones.map((z) => z.kind);
    expect(kinds).not.toContain('premium');
    expect(kinds).not.toContain('ote');
    expect(DEFAULT_OVERLAYS).toEqual({
      structure: true,
      liquidity: true,
      fvg: true,
      orderBlocks: true,
      premiumDiscount: false,
      ote: false,
    });
  });

  it('hides invalidated zones and ended pools; fades mitigated zones', () => {
    const model = buildOverlayModel(readySnapshot(), ALL_ON);
    expect(model.zones.find((z) => z.id.includes('bearish_fvg'))).toBeUndefined();
    expect(model.lines.find((l) => l.id.includes('pool:sell'))).toBeUndefined();
    expect(model.zones.find((z) => z.kind === 'ob-bull')?.faded).toBe(true);
  });

  it('never contains trade signals', () => {
    const model = buildOverlayModel(readySnapshot(), ALL_ON);
    const texts = [...model.labels.map((l) => l.text), ...model.zones.map((z) => z.label ?? '')];
    for (const text of texts) {
      expect(text).not.toMatch(/\b(BUY|SELL|Entry|SL|TP\d?)\b/);
    }
  });
});
