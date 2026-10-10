import type { OpportunityDTO } from '@/types/strategy43';
import type { SignalDTO, SignalEvaluationDTO, SignalView, StrategyInfo } from '@/types/signal';

export const SIGNAL_EVENTS = [
  'signal.developing',
  'signal.confirmed',
  'signal.updated',
  'signal.closed',
] as const;
export type SignalEventType = (typeof SIGNAL_EVENTS)[number];

export function emptyView(symbol: string, timeframe: string): SignalView {
  return {
    symbol,
    timeframe,
    strategy: null,
    evaluation: null,
    developing: null,
    active: null,
    lastConfirmed: null,
    lastClosed: null,
  };
}

const FINAL = new Set(['tp3_hit', 'stopped', 'invalidated', 'expired', 'closed']);

function newer(a: SignalEvaluationDTO | null, b: SignalEvaluationDTO): boolean {
  return a?.candle_time == null || b.candle_time == null || b.candle_time >= a.candle_time;
}

/**
 * Applies one `signal.*` event. Pure. Events for another symbol/timeframe (late events
 * after a switch) and older evaluations are ignored. Display only: nothing is computed.
 */
export function applySignalEvent(
  view: SignalView | null,
  type: string,
  data: Record<string, unknown>,
  expected: { symbol: string; timeframe: string },
): SignalView | null {
  if (data.symbol !== expected.symbol || data.timeframe !== expected.timeframe) return view;
  const prev = view ?? emptyView(expected.symbol, expected.timeframe);
  const strategy = (data.strategy as StrategyInfo | undefined) ?? prev.strategy;
  const withStrategy = strategy === prev.strategy ? prev : { ...prev, strategy };
  const base =
    'best' in data
      ? { ...withStrategy, best: (data.best as OpportunityDTO | null | undefined) ?? null }
      : withStrategy;
  const signal = (data.signal as SignalDTO | undefined) ?? null;
  const evaluation = (data.evaluation as SignalEvaluationDTO | undefined) ?? null;
  switch (type) {
    case 'signal.developing':
      return evaluation ? { ...base, developing: evaluation } : base;
    case 'signal.confirmed':
      return signal ? { ...base, active: signal, lastConfirmed: signal, developing: null } : base;
    case 'signal.closed':
      if (!signal) return base;
      return {
        ...base,
        active: base.active?.id === signal.id ? null : base.active,
        lastClosed: signal,
        lastConfirmed: base.lastConfirmed?.id === signal.id ? signal : base.lastConfirmed,
      };
    case 'signal.updated': {
      if ('active' in data || 'last_confirmed' in data) {
        // Full state (sent on subscribe / from REST).
        return {
          ...base,
          evaluation: evaluation ?? base.evaluation,
          developing: (data.developing as SignalEvaluationDTO | null | undefined) ?? null,
          active: (data.active as SignalDTO | null | undefined) ?? null,
          lastConfirmed:
            (data.last_confirmed as SignalDTO | null | undefined) ?? base.lastConfirmed,
        };
      }
      if (evaluation) {
        return newer(base.evaluation, evaluation)
          ? { ...base, evaluation, developing: null }
          : base;
      }
      if (signal) {
        if (FINAL.has(signal.state)) {
          return {
            ...base,
            active: base.active?.id === signal.id ? null : base.active,
            lastClosed: signal,
          };
        }
        const isActive = !base.active || base.active.id === signal.id;
        return {
          ...base,
          active: isActive ? signal : base.active,
          lastConfirmed: base.lastConfirmed?.id === signal.id ? signal : base.lastConfirmed,
        };
      }
      return base;
    }
    default:
      return base;
  }
}
