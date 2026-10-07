import { create } from 'zustand';

import type { ChartId } from '@/stores/layoutStore';
import type { AnalysisSnapshot } from '@/types/analysis';
import type { SignalView } from '@/types/signal';

interface AnalysisState {
  /** Latest backend analysis per chart (null while loading / after a switch). */
  byChart: Record<ChartId, AnalysisSnapshot | null>;
  /** Latest signal view per chart (null while loading / after a switch). */
  signals: Record<ChartId, SignalView | null>;
  /** Which chart the analysis panel describes. Not persisted. */
  focused: ChartId;
  /** Chart candles are (re)loading after a symbol/timeframe change (UI feedback only). */
  loading: Record<ChartId, boolean>;
  setLoading: (chart: ChartId, loading: boolean) => void;
  setAnalysis: (chart: ChartId, snapshot: AnalysisSnapshot | null) => void;
  setSignal: (chart: ChartId, view: SignalView | null) => void;
  setFocused: (chart: ChartId) => void;
}

export const useAnalysisStore = create<AnalysisState>()((set) => ({
  byChart: { primary: null, secondary: null },
  signals: { primary: null, secondary: null },
  focused: 'primary',
  loading: { primary: false, secondary: false },
  setLoading: (chart, loading) => {
    set((s) =>
      s.loading[chart] === loading ? s : { loading: { ...s.loading, [chart]: loading } },
    );
  },
  setSignal: (chart, view) => {
    set((s) => ({ signals: { ...s.signals, [chart]: view } }));
  },
  setAnalysis: (chart, snapshot) => {
    set((s) => ({ byChart: { ...s.byChart, [chart]: snapshot } }));
  },
  setFocused: (focused) => {
    set({ focused });
  },
}));
