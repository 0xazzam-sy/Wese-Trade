import type { SignalClass, SignalDTO, SignalEvaluationDTO, SignalView } from '@/types/signal';

export interface SignalDisplay {
  kind: 'confirmed' | 'developing' | 'evaluation' | 'none';
  signalClass: SignalClass;
  score: number | null;
  /** Reason shown when NEUTRAL. */
  neutralReason: string | null;
  signal: SignalDTO | null;
  evaluation: SignalEvaluationDTO | null;
}

/**
 * What the panel shows, by priority: an active confirmed signal, then a developing
 * hypothesis (never presented as confirmed), then the last closed-candle evaluation.
 */
export function signalDisplay(view: SignalView | null): SignalDisplay {
  if (view?.active) {
    return {
      kind: 'confirmed',
      signalClass: view.active.signal_class,
      score: view.active.score,
      neutralReason: null,
      signal: view.active,
      evaluation: null,
    };
  }
  const dev = view?.developing;
  if (dev && dev.signal_class !== 'NEUTRAL') {
    return {
      kind: 'developing',
      signalClass: dev.signal_class,
      score: dev.score,
      neutralReason: null,
      signal: null,
      evaluation: dev,
    };
  }
  const ev = view?.evaluation;
  if (ev) {
    return {
      kind: 'evaluation',
      signalClass: ev.signal_class,
      score: ev.signal_class === 'NEUTRAL' ? null : ev.score,
      neutralReason: ev.neutral_reason,
      signal: null,
      evaluation: ev,
    };
  }
  return {
    kind: 'none',
    signalClass: 'NEUTRAL',
    score: null,
    neutralReason: null,
    signal: null,
    evaluation: null,
  };
}
