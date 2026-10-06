import type { SignalDTO, SignalView, StrategyInfo } from '@/types/signal';

/**
 * Chart BUY/SELL markers. The ONLY source is the frozen forward-test signal engine:
 * confirmed signals persisted by the backend (REST history) plus the same signals received
 * live over the WebSocket. Nothing here looks at structure labels (HH/HL/BOS/CHoCH/OB/FVG…),
 * indicators or developing hypotheses, and nothing is reconstructed from candle history.
 */

/** Timeframes on which the forward test emits directional signals (backend TIMEFRAMES). */
export const SIGNAL_TIMEFRAMES: readonly string[] = ['15m', '30m', '1h'];

export function isSignalTimeframe(timeframe: string): boolean {
  return SIGNAL_TIMEFRAMES.includes(timeframe);
}

const FINAL_STATES = new Set(['tp3_hit', 'stopped', 'invalidated', 'expired', 'closed']);

/** An open signal (confirmed, waiting for entry, or in the trade) — not closed history. */
export function isOpenSignal(signal: SignalDTO): boolean {
  return !FINAL_STATES.has(signal.state);
}

function directional(signal: SignalDTO): boolean {
  // Only confirmed BUY / SELL exist on the chart (STRONG_* are disabled in the frozen strategy).
  return signal.signal_class === 'BUY' || signal.signal_class === 'SELL';
}

/**
 * Persisted history + live view of ONE chart stream, de-duplicated by signal id (ids are
 * deterministic, so a WebSocket reconnect, a chart reload or an app restart can never add a
 * second marker). For the same id the most recent lifecycle state wins.
 */
export function mergeChartSignals(
  history: readonly SignalDTO[],
  view: SignalView | null,
  symbol: string,
  timeframe: string,
): SignalDTO[] {
  if (!isSignalTimeframe(timeframe)) return [];
  const byId = new Map<string, SignalDTO>();
  const live = view?.symbol === symbol && view.timeframe === timeframe ? view : null;
  const sources = [...history, live?.lastClosed, live?.lastConfirmed, live?.active];
  for (const s of sources) {
    if (s?.symbol !== symbol || s.timeframe !== timeframe || !directional(s)) continue;
    const prev = byId.get(s.id);
    if (!prev || s.state_time >= prev.state_time) byId.set(s.id, s);
  }
  return [...byId.values()].sort((a, b) => a.trigger_time - b.trigger_time);
}

/** The open signal of the stream (latest confirmed one still open), if any. */
export function openSignal(signals: readonly SignalDTO[]): SignalDTO | null {
  for (let i = signals.length - 1; i >= 0; i -= 1) {
    const s = signals[i];
    if (s && isOpenSignal(s)) return s;
  }
  return null;
}

export interface MarkerSpec {
  id: string;
  /** Open time of the confirmation candle (the candle the engine confirmed the signal on). */
  time: number;
  side: 'long' | 'short';
  position: 'belowBar' | 'aboveBar';
  shape: 'arrowUp' | 'arrowDown';
  text: string;
  active: boolean;
}

export const MARKER_TEXT = { long: 'BUY · شراء', short: 'SELL · بيع' } as const;

/**
 * Marker drawables. `hasCandle` keeps markers to candles that are actually loaded on this
 * chart (a marker on a missing bar would be misplaced).
 */
export function buildMarkerSpecs(
  signals: readonly SignalDTO[],
  enabled: boolean,
  hasCandle: (time: number) => boolean = () => true,
): MarkerSpec[] {
  if (!enabled) return [];
  return signals
    .filter((s) => hasCandle(s.trigger_time))
    .map((s) => ({
      id: s.id,
      time: s.trigger_time,
      side: s.side,
      position: s.side === 'long' ? 'belowBar' : 'aboveBar',
      shape: s.side === 'long' ? 'arrowUp' : 'arrowDown',
      text: MARKER_TEXT[s.side],
      active: isOpenSignal(s),
    }));
}

/** What the per-chart status card says (BUY/SELL only from an open confirmed signal). */
export type ChartSignalState = 'buy' | 'sell' | 'neutral' | 'research' | 'paused';

export function chartSignalState(
  timeframe: string,
  open: SignalDTO | null,
  strategy: StrategyInfo | null,
): ChartSignalState {
  if (!isSignalTimeframe(timeframe)) return 'research';
  if (open) return open.side === 'long' ? 'buy' : 'sell';
  if (strategy && !strategy.signal_capable) return 'paused';
  return 'neutral';
}
