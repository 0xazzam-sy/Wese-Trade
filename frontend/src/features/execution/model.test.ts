import { describe, expect, it } from 'vitest';

import { DEFAULT_OVERLAYS } from '@/stores/overlayStore';
import { execSignal, execState } from '@/test/executionFixture';

import {
  displayPlan,
  executionMarkers,
  executionPlanLines,
  isExecutionTimeframe,
  levelLines,
} from './model';

describe('execution chart model', () => {
  it('execution timeframes are 1m / 5m / 10m only', () => {
    expect(['1m', '5m', '10m'].every(isExecutionTimeframe)).toBe(true);
    expect(['15m', '30m', '1h'].some(isExecutionTimeframe)).toBe(false);
  });

  it('BUY marker sits below the exact confirmation candle (closed-candle open time)', () => {
    const state = execState('BUY');
    const [m] = executionMarkers(state, true, () => true);
    expect(m).toMatchObject({
      time: state.signal?.candle_time,
      side: 'long',
      position: 'belowBar',
      shape: 'arrowUp',
      text: 'BUY · شراء',
      active: true,
    });
    expect(executionMarkers(state, false)).toEqual([]);
    expect(executionMarkers(state, true, () => false)).toEqual([]); // candle not loaded
  });

  it('SELL marker sits above the candle; finished signals stay as muted history', () => {
    const state = execState('NO_SETUP', {
      markers: [{ id: 's', time: 100, side: -1, state: 'stopped' }],
    });
    expect(executionMarkers(state, true)[0]).toMatchObject({
      position: 'aboveBar',
      shape: 'arrowDown',
      text: 'SELL · بيع',
      active: false,
    });
  });

  it('plan lines: confirmed plan solid from the signal candle; WAIT preview dashed', () => {
    const buy = executionPlanLines(execState('BUY'), DEFAULT_OVERLAYS);
    expect(buy.map((l) => l.kind)).toEqual([
      'plan-entry', 'plan-stop', 'plan-target', 'plan-target', 'plan-target',
    ]); // prettier-ignore
    expect(buy[0]).toMatchObject({ price: 2483.9, dashed: false, from: 1_789_718_700 });
    const wait = executionPlanLines(execState('WAIT'), DEFAULT_OVERLAYS);
    expect(wait.every((l) => l.dashed)).toBe(true);
    expect(executionPlanLines(execState('NO_SETUP'), DEFAULT_OVERLAYS)).toEqual([]);
    expect(executionPlanLines(execState('ENTRY_MISSED'), DEFAULT_OVERLAYS)).toEqual([]);
    expect(executionPlanLines(execState('BUY'), { ...DEFAULT_OVERLAYS, tradePlan: false })).toEqual(
      [],
    );
  });

  it('targets already hit are drawn faded', () => {
    const state = execState('BUY', { signal: execSignal({ state: 'tp1_hit', targets_hit: 1 }) });
    const tp = executionPlanLines(state, DEFAULT_OVERLAYS).filter((l) => l.kind === 'plan-target');
    expect(tp.map((l) => l.faded)).toEqual([true, false, false]);
  });

  it('S/R lines carry the level strength; weak levels are not drawn', () => {
    const state = execState('WAIT');
    state.overlay?.levels.push({ price: 1, strength: 1, grade: 'weak', kind: 'support' });
    const lines = levelLines(state, DEFAULT_OVERLAYS, 0);
    expect(lines.map((l) => l.label)).toEqual(['دعم قوي · 8.4', 'مقاومة متوسط · 4.1']);
    expect(levelLines(state, { ...DEFAULT_OVERLAYS, levels: false }, 0)).toEqual([]);
  });

  it('display plan: the frozen signal plan when confirmed, the parent preview otherwise', () => {
    expect(displayPlan(execState('BUY'))?.entry).toBe(2483.9);
    expect(displayPlan(execState('WAIT'))?.parent_entry).toBe(2485.14);
    expect(displayPlan(execState('NO_SETUP'))).toBeNull();
  });
});
