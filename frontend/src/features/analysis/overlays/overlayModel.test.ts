import { describe, expect, it } from 'vitest';

import { DEFAULT_OVERLAYS, type OverlayToggles } from '@/stores/overlayStore';
import { notReady, readySnapshot } from '@/test/analysisFixture';
import { PLAN, signal } from '@/test/signalFixture';

import { buildOverlayModel, tradePlanLines } from './overlayModel';

const ALL_ON: OverlayToggles = {
  structure: true,
  liquidity: true,
  fvg: true,
  orderBlocks: true,
  premiumDiscount: true,
  ote: true,
  signals: true,
  tradePlan: true,
};
const ALL_OFF: OverlayToggles = {
  structure: false,
  liquidity: false,
  fvg: false,
  orderBlocks: false,
  premiumDiscount: false,
  ote: false,
  signals: false,
  tradePlan: false,
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
      signals: true,
      tradePlan: true,
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

describe('tradePlanLines', () => {
  it('draws Entry/SL/TP1-3 of the open signal with Arabic labels', () => {
    const lines = tradePlanLines(signal(), ALL_ON);
    expect(lines.map((l) => [l.kind, l.price, l.label])).toEqual([
      ['plan-entry', 100, 'الدخول ENTRY'],
      ['plan-stop', 98, 'وقف الخسارة SL'],
      ['plan-target', 102, 'الهدف 1 TP1'],
      ['plan-target', 103.5, 'الهدف 2 TP2'],
      ['plan-target', 106, 'الهدف 3 TP3'],
    ]);
    expect(lines.every((l) => l.from === signal().trigger_time && l.to === null)).toBe(true);
  });

  it('fades hit targets; draws nothing without an open signal', () => {
    const hit = tradePlanLines(signal({ targets_hit: 1 }), ALL_ON);
    expect(hit.find((l) => l.label === 'الهدف 1 TP1')?.faded).toBe(true);
    expect(hit.find((l) => l.label === 'الهدف 2 TP2')?.faded).toBe(false);
    expect(tradePlanLines(null, ALL_ON)).toEqual([]);
  });

  it('draws a zone entry as edges until filled', () => {
    const plan = { ...PLAN, entry_model: 'ZONE_ENTRY' as const, entry_low: 99, entry_high: 100.5 };
    const lines = tradePlanLines(signal({ plan, state: 'confirmed', entry_price: null }), ALL_ON);
    expect(lines.filter((l) => l.kind === 'plan-entry').map((l) => l.price)).toEqual([
      100, 99, 100.5,
    ]);
  });

  it('respects the tradePlan toggle', () => {
    expect(tradePlanLines(signal(), { ...ALL_ON, tradePlan: false })).toEqual([]);
  });

  it('is merged into the analysis model, which never draws BUY/SELL labels itself', () => {
    const model = buildOverlayModel(readySnapshot(), ALL_OFF, signal());
    expect(model.lines).toEqual([]);
    const on = buildOverlayModel(readySnapshot(), ALL_ON, signal());
    expect(on.lines.some((l) => l.kind === 'plan-stop')).toBe(true);
    expect(on.labels.some((l) => /BUY|SELL|شراء|بيع/.test(l.text))).toBe(false);
    // plan lines do not depend on the analysis being ready
    const loading = buildOverlayModel(null, ALL_ON, signal());
    expect(loading.zones).toEqual([]);
    expect(loading.labels).toEqual([]);
    expect(loading.lines.map((l) => l.kind)).toEqual([
      'plan-entry',
      'plan-stop',
      'plan-target',
      'plan-target',
      'plan-target',
    ]);
    expect(buildOverlayModel(null, ALL_ON, null)).toEqual({ zones: [], lines: [], labels: [] });
  });
});
