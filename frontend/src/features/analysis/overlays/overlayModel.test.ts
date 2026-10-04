import { describe, expect, it } from 'vitest';

import { DEFAULT_OVERLAYS, type OverlayToggles } from '@/stores/overlayStore';
import { notReady, readySnapshot } from '@/test/analysisFixture';
import { evaluation, PLAN, signal, view } from '@/test/signalFixture';

import { buildOverlayModel, signalOverlay } from './overlayModel';

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

describe('signalOverlay', () => {
  it('draws a confirmed marker with class and score, plus Entry/SL/TP lines', () => {
    const active = signal();
    const out = signalOverlay(view({ active, lastConfirmed: active }), ALL_ON, null);
    expect(out.labels).toHaveLength(1);
    expect(out.labels[0]).toMatchObject({ text: 'شراء 78', tone: 'bull', faded: false });
    const kinds = out.lines.map((l) => [l.kind, l.price, l.label]);
    expect(kinds).toEqual([
      ['plan-entry', 100, 'دخول'],
      ['plan-stop', 98, 'وقف الخسارة'],
      ['plan-target', 102, 'TP1'],
      ['plan-target', 103.5, 'TP2'],
      ['plan-target', 106, 'TP3'],
    ]);
  });

  it('fades hit targets and closed signals; draws no plan for closed signals', () => {
    const closed = signal({
      id: 'old',
      state: 'stopped',
      signal_class: 'STRONG_SELL',
      side: 'short',
    });
    const out = signalOverlay(view({ lastClosed: closed }), ALL_ON, null);
    expect(out.labels[0]).toMatchObject({ text: 'بيع قوي 78', faded: true, position: 'above' });
    expect(out.lines).toEqual([]);
    const hit = signalOverlay(view({ active: signal({ targets_hit: 1 }) }), ALL_ON, null);
    expect(hit.lines.find((l) => l.label === 'TP1')?.faded).toBe(true);
    expect(hit.lines.find((l) => l.label === 'TP2')?.faded).toBe(false);
  });

  it('draws a developing hypothesis faded with "؟" and never as plan lines', () => {
    const dev = evaluation({ developing: true, signal_class: 'BUY', side: 'long', plan: PLAN });
    const out = signalOverlay(view({ developing: dev }), ALL_ON, 1_700_000_900);
    expect(out.labels).toEqual([
      expect.objectContaining({ text: 'شراء؟', faded: true, time: 1_700_000_900 }),
    ]);
    expect(out.lines).toEqual([]);
  });

  it('draws a zone entry as edges until filled', () => {
    const plan = { ...PLAN, entry_model: 'ZONE_ENTRY' as const, entry_low: 99, entry_high: 100.5 };
    const out = signalOverlay(
      view({ active: signal({ plan, state: 'confirmed', entry_price: null }) }),
      ALL_ON,
      null,
    );
    expect(out.lines.filter((l) => l.kind === 'plan-entry').map((l) => l.price)).toEqual([
      100, 99, 100.5,
    ]);
  });

  it('respects the signals and tradePlan toggles', () => {
    const v = view({ active: signal() });
    expect(signalOverlay(v, ALL_OFF, null)).toEqual({ lines: [], labels: [] });
    expect(signalOverlay(v, { ...ALL_OFF, signals: true }, null).lines).toEqual([]);
    expect(signalOverlay(v, { ...ALL_OFF, tradePlan: true }, null).labels).toEqual([]);
  });

  it('is merged into the analysis model', () => {
    const model = buildOverlayModel(readySnapshot(), ALL_OFF, view({ active: signal() }));
    expect(model.lines).toEqual([]);
    const on = buildOverlayModel(readySnapshot(), ALL_ON, view({ active: signal() }));
    expect(on.lines.some((l) => l.kind === 'plan-stop')).toBe(true);
    expect(buildOverlayModel(null, ALL_ON, view({ active: signal() }))).toEqual({
      zones: [],
      lines: [],
      labels: [],
    });
  });
});
